import logging
import sys
from typing import Optional
import colorlog
from src.configuration.config import settings


class Logger:
    """Centralized logging utility for the application"""
    
    def __init__(self, name: str = __name__):
        self.name = name
        self._logger: Optional[logging.Logger] = None
    
    def setup_logger(self) -> logging.Logger:
        """Set up and configure the logger"""
        if self._logger is not None:
            return self._logger
        
        # Create logger
        self._logger = logging.getLogger(self.name)
        
        # Set log level based on environment
        log_level = logging.DEBUG if settings.environment == "development" else logging.INFO
        self._logger.setLevel(log_level)
        
        # Avoid duplicate handlers
        if not self._logger.handlers:
            # Create console handler
            console_handler = colorlog.StreamHandler(sys.stdout)
            console_handler.setLevel(log_level)
            
            # Create colorful formatter - always use colors!
            formatter = colorlog.ColoredFormatter(
                '%(log_color)s%(asctime)s - %(name)s - %(levelname)s - %(message)s%(reset)s',
                datefmt='%Y-%m-%d %H:%M:%S',
                log_colors={
                    'DEBUG': 'cyan',
                    'INFO': 'green',
                    'WARNING': 'yellow',
                    'ERROR': 'red',
                    'CRITICAL': 'bold_red',
                },
                secondary_log_colors={},
                style='%'
            )
            
            console_handler.setFormatter(formatter)
            self._logger.addHandler(console_handler)
        
        return self._logger
    
    @property
    def logger(self) -> logging.Logger:
        """Get the configured logger instance"""
        if self._logger is None:
            return self.setup_logger()
        return self._logger


# Global logger instance
def get_logger(name: str = __name__) -> logging.Logger:
    """Get a logger instance for the given name"""
    logger_instance = Logger(name)
    return logger_instance.logger


# Default application logger
app_logger = get_logger("app")
