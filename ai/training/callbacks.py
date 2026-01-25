"""
Training callbacks for AI
"""


class Callback:
    """Base callback class for training"""
    
    def on_train_start(self):
        pass
    
    def on_episode_start(self, episode):
        pass
    
    def on_step_end(self, step, reward):
        pass
    
    def on_episode_end(self, episode, total_reward):
        pass
    
    def on_train_end(self):
        pass