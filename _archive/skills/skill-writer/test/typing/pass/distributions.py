import torch
from torch import Tensor, distributions
from typing_extensions import assert_type

dist = distributions.Normal(0, 1)
assert_type(dist.mean, Tensor)

dist = distributions.MultivariateNormal(torch.zeros(2), torch.eye(2))
assert_type(dist.covariance_matrix, Tensor)
