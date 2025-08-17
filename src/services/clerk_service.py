from typing import Optional, Dict, Any
from datetime import datetime
import jwt
from jwt import PyJWKClient
import base64
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.configuration.config import settings
from src.models.user import User
from src.models.subscription_plan import SubscriptionPlan
from src.models.user_subscription import UserSubscription
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ClerkService:
    """Service for interacting with Clerk API and managing users"""
    
    def __init__(self):
        # Extract domain from publishable key for JWKS URL
        # Format: pk_test_<base64_encoded_domain>
        if settings.clerk_publishable_key:
            try:
                # Remove pk_test_ prefix
                encoded_part = settings.clerk_publishable_key.replace('pk_test_', '')
                # Decode base64 to get the domain
                decoded_domain = base64.b64decode(encoded_part).decode('utf-8')
                # Remove any trailing $ if present
                domain = decoded_domain.rstrip('$')
                self.jwks_url = f"https://{domain}/.well-known/jwks.json"
            except Exception as e:
                logger.error(f"Failed to decode Clerk publishable key: {e}")
                self.jwks_url = ""
        else:
            self.jwks_url = ""
            
        logger.info(f"Using JWKS URL: {self.jwks_url}")
        self.jwks_client = PyJWKClient(self.jwks_url) if self.jwks_url else None
    
    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify a Clerk JWT token and return user data"""
        if not self.jwks_client:
            logger.error("JWKS client not initialized - check CLERK_PUBLISHABLE_KEY")
            return None
            
        try:
            # Get the signing key
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)
            
            # Decode and verify the JWT
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                options={"verify_exp": True, "verify_aud": False}
            )
            
            return payload
                
        except jwt.ExpiredSignatureError:
            logger.warning("Token has expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid token: {e}")
            return None
        except Exception as e:
            logger.error(f"Error verifying token: {e}")
            return None
    

    
    def _parse_last_sign_in(self, last_sign_in_value: Any) -> Optional[datetime]:
        """Parse last_sign_in timestamp from JWT"""
        if not last_sign_in_value:
            return None
            
        try:
            if isinstance(last_sign_in_value, int):
                # Check for invalid/null timestamps
                if last_sign_in_value <= 0:
                    return None
                elif last_sign_in_value > 10**10:  # milliseconds
                    return datetime.fromtimestamp(last_sign_in_value / 1000)
                else:  # seconds
                    return datetime.fromtimestamp(last_sign_in_value)
            elif isinstance(last_sign_in_value, str):
                # ISO format string
                return datetime.fromisoformat(last_sign_in_value.replace('Z', '+00:00'))
        except (ValueError, TypeError, OSError):
            pass
        
        return None
    
    async def get_or_create_user_from_jwt(self, db: AsyncSession, jwt_data: Dict[str, Any]) -> Optional[User]:
        """Get user from database or create from JWT claims"""
        clerk_id = jwt_data.get("user_id")
        if not clerk_id:
            return None
        
        # Try to get existing user
        result = await db.execute(select(User).where(User.clerk_id == clerk_id))
        user = result.scalar_one_or_none()
        
        # Parse timestamp once
        last_sign_in_at = self._parse_last_sign_in(jwt_data.get("last_sign_in"))
        
        if user:
            # Update existing user with fresh JWT data
            user.email = jwt_data.get("email", user.email)
            user.first_name = jwt_data.get("first_name", user.first_name)
            user.last_name = jwt_data.get("last_name", user.last_name)
            user.profile_image_url = jwt_data.get("image_url", user.profile_image_url)
            user.last_sign_in_at = last_sign_in_at
            
            logger.info(f"Updated user: {user.email}")
        else:
            # Create new user
            user = User(
                clerk_id=clerk_id,
                email=jwt_data.get("email", ""),
                first_name=jwt_data.get("first_name"),
                last_name=jwt_data.get("last_name"),
                profile_image_url=jwt_data.get("image_url"),
                last_sign_in_at=last_sign_in_at,
                credits_balance=1  # Start with 1 credit from free plan
            )
            
            db.add(user)
            await db.commit()  # Commit user first to get ID
            await db.refresh(user)
            
            # Auto-assign free plan to new users
            await self._assign_free_plan(db, user)
            
            logger.info(f"Created user: {user.email} with free plan")
        
        await db.commit()
        await db.refresh(user)
        return user
    
    async def _assign_free_plan(self, db: AsyncSession, user: User) -> None:
        """Assign the free plan to a new user"""
        try:
            # Get the free plan (ID: 1, price = 0)
            free_plan_result = await db.execute(
                select(SubscriptionPlan).where(SubscriptionPlan.id == 1)
            )
            free_plan = free_plan_result.scalar_one_or_none()
            
            if not free_plan:
                logger.warning("Free plan not found - user created without subscription")
                return
            
            # Create a "subscription" for the free plan
            # Note: This is not a real Stripe subscription since it's free
            user_subscription = UserSubscription(
                user_id=user.id,
                plan_id=free_plan.id,
                stripe_subscription_id=f"free_{user.id}_{int(datetime.now().timestamp())}",  # Fake ID
                stripe_customer_id=f"free_customer_{user.id}",  # Fake customer ID for free plan
                status="active",  # Free plan is immediately active
                current_period_start=datetime.now(),
                current_period_end=datetime(2099, 12, 31),  # Free plan doesn't expire (far future)
                cancel_at_period_end=False,
                canceled_at=None
            )
            
            db.add(user_subscription)
            await db.commit()
            
            logger.info(f"Assigned free plan to user {user.email}")
            
        except Exception as e:
            logger.error(f"Failed to assign free plan to user {user.email}: {e}")
            # Don't fail user creation if free plan assignment fails
            await db.rollback()


# Global instance
clerk_service = ClerkService()
