from __future__ import annotations

import abc
import logging


class BaseAgent(abc.ABC):
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(name)

    @abc.abstractmethod
    def run(self, **kwargs):
        raise NotImplementedError

