import redis
from src.configuration.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

class RedisCreditService:
    """Redis-based credit reservation service for high-concurrency scenarios"""
    
    def __init__(self):
        self.redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    
    def _get_user_credit_key(self, user_id: int) -> str:
        """Get Redis key for user credits"""
        return f"user_credits:{user_id}"
    
    def _get_user_reserved_key(self, user_id: int) -> str:
        """Get Redis key for user reserved credits"""
        return f"user_reserved:{user_id}"
    
    async def initialize_user_credits(self, user_id: int, credits: int) -> bool:
        """Initialize user credits in Redis if not exists"""
        try:
            key = self._get_user_credit_key(user_id)
            # Use SETNX to set only if key doesn't exist
            result = self.redis_client.setnx(key, credits)
            if result:
                logger.info(f"Initialized user {user_id} with {credits} credits in Redis")
                return True
            else:
                logger.info(f"User {user_id} credits already exist in Redis")
                return False
        except Exception as e:
            logger.error(f"Failed to initialize credits for user {user_id}: {e}")
            return False
    
    async def get_user_credits(self, user_id: int) -> int:
        """Get current user credit balance"""
        try:
            key = self._get_user_credit_key(user_id)
            credits = self.redis_client.get(key)
            return int(credits) if credits else 0
        except Exception as e:
            logger.error(f"Failed to get credits for user {user_id}: {e}")
            return 0
    
    async def reserve_credits_atomic(self, user_id: int, amount: int) -> bool:
        """
        Atomically reserve credits using Lua script.
        Returns True if successful, False if insufficient credits.
        """
        if amount <= 0:
            return True
        
        # Lua script for atomic credit reservation
        lua_script = """
        local user_key = KEYS[1]
        local reserved_key = KEYS[2]
        local amount = tonumber(ARGV[1])
        
        -- Get current credits
        local current_credits = tonumber(redis.call('GET', user_key) or 0)
        
        -- Check if sufficient credits
        if current_credits < amount then
            return 0  -- Insufficient credits
        end
        
        -- Reserve credits atomically
        redis.call('DECRBY', user_key, amount)
        redis.call('INCRBY', reserved_key, amount)
        
        return 1  -- Success
        """
        
        try:
            user_key = self._get_user_credit_key(user_id)
            reserved_key = self._get_user_reserved_key(user_id)
            
            # Execute Lua script atomically
            result = self.redis_client.eval(lua_script, 2, user_key, reserved_key, amount)
            
            if result == 1:
                logger.info(f"Reserved {amount} credits for user {user_id}")
                return True
            else:
                logger.info(f"Insufficient credits for user {user_id}. Required: {amount}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to reserve credits for user {user_id}: {e}")
            return False
    
    async def confirm_credit_usage_atomic(self, user_id: int, amount: int) -> bool:
        """
        Confirm credit usage after successful processing.
        Move from reserved to used.
        """
        if amount <= 0:
            return True
        
        # Lua script for confirming credit usage
        lua_script = """
        local reserved_key = KEYS[1]
        local amount = tonumber(ARGV[1])
        
        -- Get current reserved credits
        local reserved_credits = tonumber(redis.call('GET', reserved_key) or 0)
        
        -- Reduce reserved credits
        if reserved_credits >= amount then
            redis.call('DECRBY', reserved_key, amount)
            return 1
        else
            return 0  -- Not enough reserved credits
        end
        """
        
        try:
            reserved_key = self._get_user_reserved_key(user_id)
            
            # Execute Lua script atomically
            result = self.redis_client.eval(lua_script, 1, reserved_key, amount)
            
            if result == 1:
                logger.info(f"Confirmed {amount} credits usage for user {user_id}")
                return True
            else:
                logger.warning(f"Failed to confirm {amount} credits for user {user_id} - insufficient reserved")
                return False
                
        except Exception as e:
            logger.error(f"Failed to confirm credits for user {user_id}: {e}")
            return False
    
    async def refund_credits_atomic(self, user_id: int, amount: int) -> bool:
        """
        Refund credits if processing failed.
        Move from reserved back to available.
        """
        if amount <= 0:
            return True
        
        # Lua script for refunding credits
        lua_script = """
        local user_key = KEYS[1]
        local reserved_key = KEYS[2]
        local amount = tonumber(ARGV[1])
        
        -- Get current reserved credits
        local reserved_credits = tonumber(redis.call('GET', reserved_key) or 0)
        
        -- Refund credits
        if reserved_credits >= amount then
            redis.call('INCRBY', user_key, amount)
            redis.call('DECRBY', reserved_key, amount)
            return 1
        else
            return 0  -- Not enough reserved credits
        end
        """
        
        try:
            user_key = self._get_user_credit_key(user_id)
            reserved_key = self._get_user_reserved_key(user_id)
            
            # Execute Lua script atomically
            result = self.redis_client.eval(lua_script, 2, user_key, reserved_key, amount)
            
            if result == 1:
                logger.info(f"Refunded {amount} credits to user {user_id}")
                return True
            else:
                logger.warning(f"Failed to refund {amount} credits for user {user_id} - insufficient reserved")
                return False
                
        except Exception as e:
            logger.error(f"Failed to refund credits for user {user_id}: {e}")
            return False
    
    async def add_credits(self, user_id: int, amount: int) -> bool:
        """Add credits to user's balance"""
        if amount <= 0:
            return True
            
        try:
            user_key = self._get_user_credit_key(user_id)
            new_balance = self.redis_client.incrby(user_key, amount)
            logger.info(f"Added {amount} credits to user {user_id}. New balance: {new_balance}")
            return True
        except Exception as e:
            logger.error(f"Failed to add {amount} credits to user {user_id}: {e}")
            return False
    
    async def sync_database_balance(self, user_id: int, db_session) -> bool:
        """Sync database credits_balance with Redis balance"""
        try:
            from src.models.user import User
            from sqlalchemy import select
            
            # Get current Redis balance
            redis_balance = await self.get_user_credits(user_id)
            
            # Update database
            result = await db_session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            
            if user:
                user.credits_balance = redis_balance
                await db_session.commit()
                logger.info(f"Synced database balance for user {user_id}: {redis_balance} credits")
                return True
            else:
                logger.warning(f"User {user_id} not found for balance sync")
                return False
                
        except Exception as e:
            logger.error(f"Failed to sync database balance for user {user_id}: {e}")
            return False

    async def get_user_stats(self, user_id: int) -> dict:
        """Get comprehensive user credit statistics"""
        try:
            user_key = self._get_user_credit_key(user_id)
            reserved_key = self._get_user_reserved_key(user_id)
            
            available = int(self.redis_client.get(user_key) or 0)
            reserved = int(self.redis_client.get(reserved_key) or 0)
            
            return {
                "user_id": user_id,
                "available_credits": available,
                "reserved_credits": reserved,
                "total_credits": available + reserved
            }
        except Exception as e:
            logger.error(f"Failed to get stats for user {user_id}: {e}")
            return {"user_id": user_id, "available_credits": 0, "reserved_credits": 0, "total_credits": 0}


# Global instance
redis_credit_service = RedisCreditService()
