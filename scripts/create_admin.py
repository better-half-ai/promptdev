#!/usr/bin/env python3
"""
Admin management CLI for PromptDev.

Usage:
    # Create admin (interactive prompts)
    python -m scripts.create_admin --db=remote
    
    # List admins
    python -m scripts.create_admin --db=remote --list
    
    # Reset password
    python -m scripts.create_admin --db=remote --email=admin@example.com --reset-password
    
    # Deactivate admin
    python -m scripts.create_admin --db=remote --email=admin@example.com --deactivate
    
    # Activate admin
    python -m scripts.create_admin --db=remote --email=admin@example.com --activate
    
    # Delete admin
    python -m scripts.create_admin --db=remote --email=admin@example.com --delete
"""

import os
import sys
import argparse
import getpass
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description="Manage PromptDev admins")
    parser.add_argument("--db", required=True, choices=["local", "remote"],
                        help="Database to use")
    parser.add_argument("--email", help="Admin email")
    parser.add_argument("--list", action="store_true", help="List all admins")
    parser.add_argument("--reset-password", action="store_true", help="Reset admin password")
    parser.add_argument("--deactivate", action="store_true", help="Deactivate admin")
    parser.add_argument("--activate", action="store_true", help="Activate admin")
    parser.add_argument("--delete", action="store_true", help="Delete admin")
    args = parser.parse_args()
    
    # Set DB_TARGET before importing db module
    os.environ["DB_TARGET"] = args.db
    
    import db.db as db
    from src.auth import create_admin, list_admins, get_admin_by_email, update_admin, delete_admin
    
    # Initialize pool
    db.init_pool()
    
    try:
        # List admins
        if args.list:
            admins = list_admins()
            if not admins:
                print("No admins found.")
            else:
                print(f"{'ID':<6} {'Email':<40} {'Active':<8} {'Created':<24} {'Last Login':<24}")
                print("-" * 110)
                for a in admins:
                    created = a['created_at'][:19] if a['created_at'] else 'N/A'
                    login = a['last_login'][:19] if a['last_login'] else 'Never'
                    print(f"{a['id']:<6} {a['email']:<40} {str(a['is_active']):<8} {created:<24} {login:<24}")
            return
        
        # For operations requiring email
        if args.deactivate or args.activate or args.delete or args.reset_password:
            if not args.email:
                print("Error: --email required for this operation")
                sys.exit(1)
        
        # Reset password
        if args.reset_password:
            admin = get_admin_by_email(args.email)
            if not admin:
                print(f"Error: Admin '{args.email}' not found")
                sys.exit(1)
            
            while True:
                password = getpass.getpass("Enter new password (min 8 chars): ")
                if len(password) < 8:
                    print("Error: Password must be at least 8 characters")
                    continue
                
                password_confirm = getpass.getpass("Confirm new password: ")
                if password != password_confirm:
                    print("Error: Passwords do not match")
                    continue
                
                break
            
            update_admin(admin["id"], password=password)
            print(f"✅ Password reset for '{args.email}'")
            return
        
        # Deactivate
        if args.deactivate:
            admin = get_admin_by_email(args.email)
            if not admin:
                print(f"Error: Admin '{args.email}' not found")
                sys.exit(1)
            update_admin(admin["id"], is_active=False)
            print(f"✅ Deactivated admin '{args.email}'")
            return
        
        # Activate
        if args.activate:
            admin = get_admin_by_email(args.email)
            if not admin:
                print(f"Error: Admin '{args.email}' not found")
                sys.exit(1)
            update_admin(admin["id"], is_active=True)
            print(f"✅ Activated admin '{args.email}'")
            return
        
        # Delete
        if args.delete:
            admin = get_admin_by_email(args.email)
            if not admin:
                print(f"Error: Admin '{args.email}' not found")
                sys.exit(1)
            delete_admin(admin["id"])
            print(f"✅ Deleted admin '{args.email}'")
            return
        
        # Create admin (default action) - interactive prompts
        email = args.email
        if not email:
            email = input("Enter email: ").strip()
            if not email:
                print("Error: Email required")
                sys.exit(1)
        
        # Check if already exists
        if get_admin_by_email(email):
            print(f"Error: Admin '{email}' already exists")
            sys.exit(1)
        
        # Prompt for password securely
        while True:
            password = getpass.getpass("Enter password (min 8 chars): ")
            if len(password) < 8:
                print("Error: Password must be at least 8 characters")
                continue
            
            password_confirm = getpass.getpass("Confirm password: ")
            if password != password_confirm:
                print("Error: Passwords do not match")
                continue
            
            break
        
        admin_id = create_admin(email, password)
        print(f"✅ Created admin '{email}' (id={admin_id}) in {args.db} database")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        db.close_pool()


if __name__ == "__main__":
    main()
