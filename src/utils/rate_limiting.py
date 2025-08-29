import redis
from datetime import datetime, timedelta

from src.utils.logger import get_logger
from src.configuration.config import settings

logger = get_logger(__name__)

# Redis client for tracking daily page usage
redis_client = redis.from_url(settings.redis_url, decode_responses=True)


async def reserve_anonymous_pages(client_ip: str, pages_to_reserve: int) -> bool:
    """Reserve pages for anonymous user. Returns True if successful, False if would exceed limit"""
    today = datetime.now().strftime("%Y-%m-%d")
    key = f"anonymous_pages:{client_ip}:{today}"
    
    try:
        # Get current usage
        current_usage = int(redis_client.get(key) or "0")
        
        # Check if reservation would exceed limit
        if current_usage + pages_to_reserve > settings.free_tier_max_pages:
            logger.info(f"Anonymous user {client_ip} reservation denied: {current_usage} + {pages_to_reserve} > {settings.free_tier_max_pages}")
            return False
        
        # Reserve the pages
        new_usage = current_usage + pages_to_reserve
        redis_client.set(key, str(new_usage))
        redis_client.expireat(key, int((datetime.now() + timedelta(days=1)).replace(hour=0, minute=0, second=0).timestamp()))
        
        logger.info(f"Anonymous user {client_ip} reserved {pages_to_reserve} pages. Total reserved today: {new_usage}")
        return True
    except Exception as e:
        logger.error(f"Failed to reserve anonymous pages for {client_ip}: {e}")
        return False


async def refund_anonymous_pages(client_ip: str, pages_to_refund: int):
    """Refund pages to anonymous user if processing failed"""
    today = datetime.now().strftime("%Y-%m-%d")
    key = f"anonymous_pages:{client_ip}:{today}"
    
    try:
        # Get current usage
        current_usage = int(redis_client.get(key) or "0")
        
        # Refund pages (don't go below 0)
        new_usage = max(0, current_usage - pages_to_refund)
        redis_client.set(key, str(new_usage))
        redis_client.expireat(key, int((datetime.now() + timedelta(days=1)).replace(hour=0, minute=0, second=0).timestamp()))
        
        logger.info(f"Anonymous user {client_ip} refunded {pages_to_refund} pages. Total reserved today: {new_usage}")
        return new_usage
    except Exception as e:
        logger.error(f"Failed to refund anonymous pages for {client_ip}: {e}")
        return 0