import sqlite3
import logging
import os

# --- Configuration ---
DATABASE_NAME = 'power_data.db'
VIEWS_SQL_FILE = 'create_views.sql' # The name of the SQL file with view definitions

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ViewManager:
    """Manages the creation and updates of database views."""

    def __init__(self, db_name: str):
        """
        Initializes the ViewManager.
        
        Args:
            db_name: The path to the SQLite database file.
        """
        self.db_name = db_name
        self.conn = None
        self.logger = logging.getLogger(self.__class__.__name__)

    def _connect(self) -> bool:
        """Establishes a database connection."""
        if not os.path.exists(self.db_name):
            self.logger.error(f"Database file '{self.db_name}' not found. Please run setup first.")
            return False
        try:
            self.conn = sqlite3.connect(self.db_name)
            self.conn.execute("PRAGMA foreign_keys = ON;")
            self.logger.info(f"Successfully connected to database {self.db_name}")
            return True
        except sqlite3.Error as e:
            self.logger.error(f"Error connecting to database: {e}")
            return False

    def _execute_sql_file(self, sql_file: str):
        """Executes a multi-statement SQL script from a file."""
        self.logger.info(f"Executing SQL script from '{sql_file}'...")
        try:
            if not os.path.exists(sql_file):
                raise FileNotFoundError(f"SQL script file not found: {sql_file}")
            with open(sql_file, 'r') as f:
                sql_script = f.read()
            self.conn.executescript(sql_script)
            self.conn.commit()
            self.logger.info(f"Successfully executed script '{sql_file}'.")
        except (FileNotFoundError, sqlite3.Error) as e:
            self.logger.error(f"Failed to execute SQL script '{sql_file}': {e}")
            self.conn.rollback() # Rollback changes on error
            raise

    def close(self):
        """Closes the database connection."""
        if self.conn:
            self.conn.close()
            self.logger.info("Database connection closed.")

    def create_or_update_views(self, views_sql_file: str):
        """
        Main public method to run the view creation process.
        
        Args:
            views_sql_file: The path to the .sql file containing CREATE VIEW statements.
        """
        self.logger.info("--- Starting View Creation Process ---")
        if self._connect():
            try:
                self._execute_sql_file(views_sql_file)
                self.logger.info("--- View Creation Completed Successfully ---")
            except Exception as e:
                self.logger.error(f"--- View Creation Failed: {e} ---", exc_info=True)
            finally:
                self.close()

if __name__ == '__main__':
    # This block makes the script directly runnable from the command line.
    view_manager = ViewManager(db_name=DATABASE_NAME)
    view_manager.create_or_update_views(views_sql_file=VIEWS_SQL_FILE)

