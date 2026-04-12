import pyodbc
import sys
import os
from typing import Optional

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("Warning: python-dotenv not installed. Install with: pip install python-dotenv")
    pass


def test_connection(
    server: str,
    database: str,
    username: str,
    password: str,
    timeout: int = 30
) -> bool:
    """
    Test SQL Server connection with the provided parameters.
    
    Args:
        server: Server name (e.g., 'powerflow-server')
        database: Database name (e.g., 'Powerflow')
        username: SQL username
        password: SQL password
        timeout: Connection timeout in seconds
    
    Returns:
        bool: True if connection successful, False otherwise
    """
    
    # Build connection string
    connection_string = (
        f"Driver={{ODBC Driver 18 for SQL Server}};"
        f"Server=tcp:{server}.database.windows.net,1433;"
        f"Database={database};"
        f"Uid={username};"
        f"Pwd={password};"
        f"Encrypt=yes;"
        f"TrustServerCertificate=no;"
        f"Connection Timeout={timeout};"
    )
    
    print("Testing connection with:")
    print(f"  Server: {server}.database.windows.net")
    print(f"  Database: {database}")
    print(f"  Username: {username}")
    print(f"  Timeout: {timeout} seconds")
    print("-" * 50)
    
    try:
        # Test connection
        print("Establishing connection...")
        with pyodbc.connect(connection_string) as conn:
            print("✅ Connection successful!")
            
            # Test basic query
            cursor = conn.cursor()
            cursor.execute("SELECT @@VERSION")
            version = cursor.fetchone()[0]
            print(f"✅ Server version: {version[:100]}...")
            
            # Test database access
            cursor.execute("SELECT DB_NAME() AS CurrentDatabase")
            current_db = cursor.fetchone()[0]
            print(f"✅ Connected to database: {current_db}")
            
            # Test table access
            cursor.execute("SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'dbo'")
            table_count = cursor.fetchone()[0]
            print(f"✅ Found {table_count} tables in dbo schema")
            
            # Test specific table if it exists
            cursor.execute("SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'DimCountries'")
            if cursor.fetchone()[0] > 0:
                cursor.execute("SELECT COUNT(*) FROM dbo.DimCountries")
                row_count = cursor.fetchone()[0]
                print(f"✅ DimCountries table exists with {row_count} rows")
            else:
                print("⚠️  DimCountries table not found (may not exist yet)")
            
            return True
            
    except pyodbc.Error as e:
        print(f"❌ Connection failed with pyodbc error:")
        print(f"   Error code: {e.args[0]}")
        print(f"   Error message: {e.args[1]}")
        
        # Provide specific guidance based on error
        if "08001" in str(e.args[0]):
            print("\n🔍 Troubleshooting: Connection timeout or network issue")
            print("   - Check if port 1433 is open")
            print("   - Verify your IP is allowed in Azure SQL firewall")
            print("   - Check server name spelling")
        elif "28000" in str(e.args[0]):
            print("\n🔍 Troubleshooting: Authentication failed")
            print("   - Verify username and password")
            print("   - Check if user exists in database")
            print("   - Ensure user has access to the database")
        elif "IM002" in str(e.args[0]):
            print("\n🔍 Troubleshooting: ODBC Driver not found")
            print("   - Install 'ODBC Driver 18 for SQL Server'")
            print("   - Verify driver name in connection string")
        
        return False
        
    except Exception as e:
        print(f"❌ Connection failed with unexpected error: {str(e)}")
        return False


def test_environment() -> bool:
    """Test if required dependencies are available."""
    print("Testing environment...")
    
    try:
        import pyodbc
        print("✅ pyodbc is available")
        
        # Check ODBC drivers
        drivers = pyodbc.drivers()
        odbc_18 = [d for d in drivers if 'ODBC Driver 18' in d]
        
        if odbc_18:
            print(f"✅ Found ODBC Driver 18: {odbc_18[0]}")
        else:
            print("❌ ODBC Driver 18 not found")
            print("   Available drivers:")
            for driver in drivers:
                print(f"     - {driver}")
            return False
            
        return True
        
    except ImportError:
        print("❌ pyodbc not installed. Install with: pip install pyodbc")
        return False
    except Exception as e:
        print(f"❌ Environment test failed: {str(e)}")
        return False


def main():
    """Main function to test SQL Server connection."""
    print("SQL Server Connection Tester")
    print("=" * 50)
    
    # Test environment first
    if not test_environment():
        print("\n❌ Environment check failed. Please fix the issues above.")
        sys.exit(1)
    
    print("\n" + "=" * 50)
    
    # Get connection parameters from .env file
    server = os.environ.get('AZURE_SQL_SERVER')
    database = os.environ.get('AZURE_SQL_DATABASE')
    username = os.environ.get('AZURE_SQL_USERNAME')
    password = os.environ.get('AZURE_SQL_PASSWORD')
    
    # Show loaded values
    print("Connection parameters from .env file:")
    print(f"  Server: {server or 'NOT SET'}")
    print(f"  Database: {database or 'NOT SET'}")
    print(f"  Username: {username or 'NOT SET'}")
    print(f"  Password: {'*' * len(password) if password else 'NOT SET'}")
    
    # Prompt for any missing values
    if not server:
        server = input("Server name (e.g., powerflow-server): ").strip()
    if not database:
        database = input("Database name (e.g., Powerflow): ").strip()
    if not username:
        username = input("Username: ").strip()
    if not password:
        password = input("Password: ").strip()
    
    # Validate inputs
    if not all([server, database, username, password]):
        print("❌ All parameters are required!")
        sys.exit(1)
    
    # Remove .database.windows.net if user included it
    if '.database.windows.net' in server:
        server = server.replace('.database.windows.net', '')
    
    print("\n" + "=" * 50)
    
    # Test connection
    success = test_connection(server, database, username, password)
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 Connection test successful! You can now run your data import scripts.")
        print("\nNext steps:")
        print("1. Run: python generate_sql_inserts.py")
        print("2. Execute the generated SQL files in SSMS")
        print("3. Or use the master file for bulk import")
    else:
        print("💥 Connection test failed. Please fix the issues above before proceeding.")
        print("\nCommon solutions:")
        print("- Check firewall settings in Azure SQL")
        print("- Verify username/password")
        print("- Ensure ODBC Driver 18 is installed")
        print("- Check server name spelling")
    
    return success


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {str(e)}")
        sys.exit(1)
