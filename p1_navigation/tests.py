import time
import numpy as np
import torch
import progressbar

# from unityagents import UnityEnvironment
from agent import Agent
import utils
from utils import LogLoader
from get_args import get_args
from PIL import Image
import torchvision.transforms as T
from collections import namedtuple, deque
from progress.bar import Bar
from progress.spinner import Spinner




for i in range(4):
    print(i)
