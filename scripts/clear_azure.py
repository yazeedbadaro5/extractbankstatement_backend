#!/usr/bin/env python3
"""
Simple Azure Storage Cleanup
Deletes all files from all containers.
"""

import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.azure_storage_service import azure_storage_service

def clear_azure():
    """Clear all Azure storage containers"""
    print("☁️  Clearing Azure Storage...")
    
    try:
        # Get all containers
        containers = azure_storage_service.blob_service_client.list_containers()
        container_names = [container.name for container in containers]
        
        if not container_names:
            print("✅ No containers found")
            return
        
        print(f"Found containers: {', '.join(container_names)}")
        
        total_deleted = 0
        
        # Clear each container
        for container_name in container_names:
            try:
                container_client = azure_storage_service.blob_service_client.get_container_client(container_name)
                blobs = list(container_client.list_blobs())
                
                if blobs:
                    print(f"Clearing {container_name}: {len(blobs)} files")
                    for blob in blobs:
                        container_client.delete_blob(blob.name)
                        total_deleted += 1
                    print(f"✅ {container_name}: Cleared")
                else:
                    print(f"✅ {container_name}: Already empty")
                    
            except Exception as e:
                print(f"❌ {container_name}: Error - {e}")
        
        print(f"\n🎉 Total files deleted: {total_deleted}")
        
    except Exception as e:
        print(f"❌ Azure error: {e}")

if __name__ == "__main__":
    clear_azure()
