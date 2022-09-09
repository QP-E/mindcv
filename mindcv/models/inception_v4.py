#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ============================================================================

from typing import Union, Tuple

import mindspore.nn as nn
import mindspore.ops as ops
import mindspore.common.initializer as init
from mindspore import Tensor

from .utils import load_pretrained
from .registry import register_model
from .layers.pooling import GlobalAvgPooling

__all__ = [
    'InceptionV4',
    'inception_v4'
]


def _cfg(url='', **kwargs):
    return {
        'url': url,
        'num_classes': 1000,
        'first_conv': '', 'classifier': '',
        **kwargs
    }


default_cfgs = {
    'inception_v4': _cfg(url='')
}


class BasicConv2d(nn.Cell):
    def __init__(self,
                 in_channels: int,
                 out_channels: int,
                 kernel_size: Union[int, Tuple] = 1,
                 stride: int = 1,
                 padding: int = 0,
                 pad_mode: str = 'same'
                 ) -> None:
        super(BasicConv2d, self).__init__()
        self.conv = nn.Conv2d(in_channels,
                              out_channels,
                              kernel_size=kernel_size,
                              stride=stride,
                              padding=padding,
                              pad_mode=pad_mode)
        self.bn = nn.BatchNorm2d(out_channels, eps=0.001, momentum=0.9997)
        self.relu = nn.ReLU()

    def construct(self, x: Tensor) -> Tensor:
        x = self.conv(x)
        x = self.bn(x)
        x = self.relu(x)
        return x


class Stem(nn.Cell):

    def __init__(self, in_channels: int) -> None:
        super(Stem, self).__init__()
        self.conv2d_1a_3x3 = BasicConv2d(in_channels, 32, kernel_size=3, stride=2, pad_mode='valid')
        self.conv2d_2a_3x3 = BasicConv2d(32, 32, kernel_size=3, stride=1, pad_mode='valid')
        self.conv2d_2b_3x3 = BasicConv2d(32, 64, kernel_size=3, stride=1, pad_mode='pad', padding=1)

        self.mixed_3a_branch_0 = nn.MaxPool2d(3, stride=2)
        self.mixed_3a_branch_1 = BasicConv2d(64, 96, kernel_size=3, stride=2, pad_mode='valid')

        self.mixed_4a_branch_0 = nn.SequentialCell([
            BasicConv2d(160, 64, kernel_size=1, stride=1),
            BasicConv2d(64, 96, kernel_size=3, stride=1, pad_mode='valid')])

        self.mixed_4a_branch_1 = nn.SequentialCell([
            BasicConv2d(160, 64, kernel_size=1, stride=1),
            BasicConv2d(64, 64, kernel_size=(1, 7), stride=1),
            BasicConv2d(64, 64, kernel_size=(7, 1), stride=1),
            BasicConv2d(64, 96, kernel_size=3, stride=1, pad_mode='valid')])

        self.mixed_5a_branch_0 = BasicConv2d(192, 192, kernel_size=3, stride=2, pad_mode='valid')
        self.mixed_5a_branch_1 = nn.MaxPool2d(3, stride=2)

    def construct(self, x: Tensor) -> Tensor:
        x = self.conv2d_1a_3x3(x)  # 149 x 149 x 32
        x = self.conv2d_2a_3x3(x)  # 147 x 147 x 32
        x = self.conv2d_2b_3x3(x)  # 147 x 147 x 64

        x0 = self.mixed_3a_branch_0(x)
        x1 = self.mixed_3a_branch_1(x)
        x = ops.concat((x0, x1), axis=1)  # 73 x 73 x 160

        x0 = self.mixed_4a_branch_0(x)
        x1 = self.mixed_4a_branch_1(x)
        x = ops.concat((x0, x1), axis=1)  # 71 x 71 x 192

        x0 = self.mixed_5a_branch_0(x)
        x1 = self.mixed_5a_branch_1(x)
        x = ops.concat((x0, x1), axis=1)  # 35 x 35 x 384
        return x


class InceptionA(nn.Cell):

    def __init__(self) -> None:
        super(InceptionA, self).__init__()
        self.branch_0 = BasicConv2d(384, 96, kernel_size=1, stride=1)
        self.branch_1 = nn.SequentialCell([
            BasicConv2d(384, 64, kernel_size=1, stride=1),
            BasicConv2d(64, 96, kernel_size=3, stride=1, pad_mode='pad', padding=1)])

        self.branch_2 = nn.SequentialCell([
            BasicConv2d(384, 64, kernel_size=1, stride=1),
            BasicConv2d(64, 96, kernel_size=3, stride=1, pad_mode='pad', padding=1),
            BasicConv2d(96, 96, kernel_size=3, stride=1, pad_mode='pad', padding=1)])

        self.branch_3 = nn.SequentialCell([
            nn.AvgPool2d(kernel_size=3, stride=1, pad_mode='same'),
            BasicConv2d(384, 96, kernel_size=1, stride=1)])

    def construct(self, x: Tensor) -> Tensor:
        x0 = self.branch_0(x)
        x1 = self.branch_1(x)
        x2 = self.branch_2(x)
        x3 = self.branch_3(x)
        x4 = ops.concat((x0, x1, x2, x3), axis=1)
        return x4


class InceptionB(nn.Cell):

    def __init__(self) -> None:
        super(InceptionB, self).__init__()
        self.branch_0 = BasicConv2d(1024, 384, kernel_size=1, stride=1)
        self.branch_1 = nn.SequentialCell([
            BasicConv2d(1024, 192, kernel_size=1, stride=1),
            BasicConv2d(192, 224, kernel_size=(1, 7), stride=1),
            BasicConv2d(224, 256, kernel_size=(7, 1), stride=1),
        ])
        self.branch_2 = nn.SequentialCell([
            BasicConv2d(1024, 192, kernel_size=1, stride=1),
            BasicConv2d(192, 192, kernel_size=(7, 1), stride=1),
            BasicConv2d(192, 224, kernel_size=(1, 7), stride=1),
            BasicConv2d(224, 224, kernel_size=(7, 1), stride=1),
            BasicConv2d(224, 256, kernel_size=(1, 7), stride=1)
        ])
        self.branch_3 = nn.SequentialCell([
            nn.AvgPool2d(kernel_size=3, stride=1, pad_mode='same'),
            BasicConv2d(1024, 128, kernel_size=1, stride=1)
        ])

    def construct(self, x: Tensor) -> Tensor:
        x0 = self.branch_0(x)
        x1 = self.branch_1(x)
        x2 = self.branch_2(x)
        x3 = self.branch_3(x)
        x4 = ops.concat((x0, x1, x2, x3), axis=1)
        return x4


class ReductionA(nn.Cell):

    def __init__(self) -> None:
        super(ReductionA, self).__init__()
        self.branch_0 = BasicConv2d(384, 384, kernel_size=3, stride=2, pad_mode='valid')
        self.branch_1 = nn.SequentialCell([
            BasicConv2d(384, 192, kernel_size=1, stride=1),
            BasicConv2d(192, 224, kernel_size=3, stride=1, pad_mode='pad', padding=1),
            BasicConv2d(224, 256, kernel_size=3, stride=2, pad_mode='valid'),
        ])
        self.branch_2 = nn.MaxPool2d(3, stride=2)

    def construct(self, x: Tensor) -> Tensor:
        x0 = self.branch_0(x)
        x1 = self.branch_1(x)
        x2 = self.branch_2(x)
        x3 = ops.concat((x0, x1, x2), axis=1)
        return x3


class ReductionB(nn.Cell):

    def __init__(self) -> None:
        super(ReductionB, self).__init__()
        self.branch_0 = nn.SequentialCell([
            BasicConv2d(1024, 192, kernel_size=1, stride=1),
            BasicConv2d(192, 192, kernel_size=3, stride=2, pad_mode='valid'),
        ])
        self.branch_1 = nn.SequentialCell([
            BasicConv2d(1024, 256, kernel_size=1, stride=1),
            BasicConv2d(256, 256, kernel_size=(1, 7), stride=1),
            BasicConv2d(256, 320, kernel_size=(7, 1), stride=1),
            BasicConv2d(320, 320, kernel_size=3, stride=2, pad_mode='valid')
        ])
        self.branch_2 = nn.MaxPool2d(3, stride=2)

    def construct(self, x: Tensor) -> Tensor:
        x0 = self.branch_0(x)
        x1 = self.branch_1(x)
        x2 = self.branch_2(x)
        x3 = ops.concat((x0, x1, x2), axis=1)
        return x3  # 8 x 8 x 1536


class InceptionC(nn.Cell):

    def __init__(self) -> None:
        super(InceptionC, self).__init__()
        self.branch_0 = BasicConv2d(1536, 256, kernel_size=1, stride=1)

        self.branch_1 = BasicConv2d(1536, 384, kernel_size=1, stride=1)
        self.branch_1_1 = BasicConv2d(384, 256, kernel_size=(1, 3), stride=1)
        self.branch_1_2 = BasicConv2d(384, 256, kernel_size=(3, 1), stride=1)

        self.branch_2 = nn.SequentialCell([
            BasicConv2d(1536, 384, kernel_size=1, stride=1),
            BasicConv2d(384, 448, kernel_size=(3, 1), stride=1),
            BasicConv2d(448, 512, kernel_size=(1, 3), stride=1),
        ])
        self.branch_2_1 = BasicConv2d(512, 256, kernel_size=(1, 3), stride=1)
        self.branch_2_2 = BasicConv2d(512, 256, kernel_size=(3, 1), stride=1)

        self.branch_3 = nn.SequentialCell([
            nn.AvgPool2d(kernel_size=3, stride=1, pad_mode='same'),
            BasicConv2d(1536, 256, kernel_size=1, stride=1)
        ])

    def construct(self, x: Tensor) -> Tensor:
        x0 = self.branch_0(x)
        x1 = self.branch_1(x)
        x1_1 = self.branch_1_1(x1)
        x1_2 = self.branch_1_2(x1)
        x1 = ops.concat((x1_1, x1_2), axis=1)
        x2 = self.branch_2(x)
        x2_1 = self.branch_2_1(x2)
        x2_2 = self.branch_2_2(x2)
        x2 = ops.concat((x2_1, x2_2), axis=1)
        x3 = self.branch_3(x)
        return ops.concat((x0, x1, x2, x3), axis=1)


class InceptionV4(nn.Cell):

    def __init__(self,
                 in_channels: int = 3,
                 num_classes: int = 1000,
                 drop_rate: float = 0.2
                 ) -> None:
        super(InceptionV4, self).__init__()
        blocks = list()
        blocks.append(Stem(in_channels))
        for _ in range(4):
            blocks.append(InceptionA())
        blocks.append(ReductionA())
        for _ in range(7):
            blocks.append(InceptionB())
        blocks.append(ReductionB())
        for _ in range(3):
            blocks.append(InceptionC())
        self.features = nn.SequentialCell(blocks)

        self.pool = GlobalAvgPooling()
        self.dropout = nn.Dropout(1 - drop_rate)
        self.num_features = 1536
        self.classifier = nn.Dense(self.num_features, num_classes)
        self._initialize_weights()

    def _initialize_weights(self) -> None:
        for _, cell in self.cells_and_names():
            if isinstance(cell, nn.Conv2d):
                cell.weight.set_data(
                    init.initializer(init.XavierUniform(),
                                     cell.weight.shape, cell.weight.dtype))

    def forward_features(self, x: Tensor) -> Tensor:
        x = self.features(x)
        return x

    def forward_head(self, x: Tensor) -> Tensor:
        x = self.pool(x)
        x = self.dropout(x)
        x = self.classifier(x)
        return x

    def construct(self, x: Tensor) -> Tensor:
        x = self.forward_features(x)
        x = self.forward_head(x)
        return x


@register_model
def inception_v4(pretrained: bool = False, num_classes: int = 1000, in_channels=3, **kwargs) -> InceptionV4:
    default_cfg = default_cfgs['inception_v4']
    model = InceptionV4(num_classes=num_classes, in_channels=in_channels, **kwargs)

    if pretrained:
        load_pretrained(model, default_cfg, num_classes=num_classes, in_channels=in_channels)

    return model