import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from run_app import DB_PATH

def reset_database():
    print(f"Target Database Path: {DB_PATH}")
    
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
            print(f"Successfully deleted database at: {DB_PATH}")
            print("Please restart the application to initialize a fresh database.")
        except Exception as e:
            print(f"Error deleting database: {e}")
            print("You may need to close any running instances of the app first.")
    else:
        print(f"No database found at {DB_PATH}. Nothing to delete.")

if __name__ == "__main__":
    confirm = input("Are you sure you want to delete the database? All data will be lost. (y/n): ")
    if confirm.lower() == 'y':
        reset_database()
    else:
        print("Operation cancelled.")
