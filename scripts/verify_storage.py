import os
import httpx
from dotenv import load_dotenv

load_dotenv("backend/.env")
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

headers = {
    "apikey": key,
    "Authorization": f"Bearer {key}",
    "Content-Type": "application/json"
}

buckets = [
    "archive-documents",
    "archive-images",
    "archive-audio",
    "archive-derivatives"
]

print("=================================================================")
print("  Supabase Storage Bucket Verification & File Inventory")
print("=================================================================")

total_files = 0
total_bytes = 0

with httpx.Client(timeout=30.0) as client:
    # 1. Verify buckets exist
    res = client.get(f"{url}/storage/v1/bucket", headers=headers)
    if res.status_code == 200:
        existing_buckets = {b["id"]: b for b in res.json()}
        for b_name in buckets:
            exists = b_name in existing_buckets
            status = "EXISTS (Public)" if (exists and existing_buckets[b_name].get("public")) else ("EXISTS" if exists else "MISSING")
            print(f"Bucket [{b_name}]: {status}")
    else:
        print(f"Failed to list buckets: HTTP {res.status_code}")

    print("\n-----------------------------------------------------------------")
    print(f"{'Bucket Name':<25} | {'Objects':<10} | {'Total Size':<15}")
    print("-----------------------------------------------------------------")

    for b_name in buckets:
        # List objects in bucket
        try:
            # Post to /object/list/{bucket}
            list_res = client.post(
                f"{url}/storage/v1/object/list/{b_name}",
                headers=headers,
                json={"prefix": "", "limit": 1000, "sortBy": {"column": "name", "order": "asc"}}
            )
            if list_res.status_code == 200:
                objects = list_res.json()
                # If there are subdirectories, also list recursive or count
                b_count = len(objects)
                b_size = sum((obj.get("metadata") or {}).get("size", 0) for obj in objects if isinstance(obj, dict))
                
                # Check subfolders if items are folders
                for obj in objects:
                    if obj.get("id") is None: # folder
                        folder_prefix = obj.get("name") + "/"
                        sub_res = client.post(
                            f"{url}/storage/v1/object/list/{b_name}",
                            headers=headers,
                            json={"prefix": folder_prefix, "limit": 1000}
                        )
                        if sub_res.status_code == 200:
                            sub_objects = sub_res.json()
                            b_count += len(sub_objects) - 1
                            b_size += sum((so.get("metadata") or {}).get("size", 0) for so in sub_objects if isinstance(so, dict))

                total_files += b_count
                total_bytes += b_size
                size_str = f"{b_size / (1024*1024):.2f} MB" if b_size >= 1024*1024 else f"{b_size / 1024:.2f} KB"
                print(f"{b_name:<25} | {b_count:<10} | {size_str:<15}")
            else:
                print(f"{b_name:<25} | ERROR {list_res.status_code}")
        except Exception as e:
            print(f"{b_name:<25} | EXCEPTION: {e}")

print("=================================================================")
total_size_mb = total_bytes / (1024 * 1024)
print(f"Grand Total: {total_files} archival assets synchronized ({total_size_mb:.2f} MB)")
