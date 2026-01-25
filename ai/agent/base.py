"""
Base agent class for AI
"""
from abc import ABC, abstractmethod


class BaseAgent(ABC):
    """Base abstract agent class"""
    
    @abstractmethod
    def act(self, state):
        """Choose an action based on the state"""
        pass
        
    @abstractmethod
    def train(self, experiences):
        """Train the agent on experiences"""
        pass