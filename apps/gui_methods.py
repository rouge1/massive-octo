# Standard library imports
import copy
import re
import logging
import os
import json

# Third-party imports
from PyQt5.QtCore import QObject, pyqtSignal

# Get logger for this module (will use root logger's handlers)
logger = logging.getLogger(__name__)
# Ensure propagation is enabled (should be by default, but make it explicit)
logger.propagate = True
# Don't set level here - let it inherit from root logger


class SignalHandler(logging.Handler, QObject):
    """Custom logging handler that emits signals for GUI updates"""
    log_signal = pyqtSignal(str)
    
    def __init__(self):
        logging.Handler.__init__(self)
        QObject.__init__(self)
    
    def emit(self, record):
        # Format the log record and emit as signal
        log_message = self.format(record)
        self.log_signal.emit(log_message)


def validate_email(email):
    """Validate email format using regex"""
    pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    return re.match(pattern, email) is not None


async def validate_url(url, browser_service):
    """Check if URL exists and is accessible"""
    try:
        logger.info("Checking if website is accessible...")
        exists, error = await browser_service.check_url_exists(url)
        return exists, error
    except Exception as e:
        return False, str(e)


def convert_seconds_to_human_readable(seconds):
    """Convert seconds to a human-readable format"""
    if seconds < 60:
        return f"{seconds} seconds"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes > 1 else ''}"
    elif seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours > 1 else ''}"
    else:
        days = seconds // 86400
        return f"{days} day{'s' if days > 1 else ''}"


def save_settings(x=None, y=None, width=None, height=None, headless=None, screenshot_viewer=None, domain_name=None, port=None, browser_x=None, browser_y=None, browser_width=None, browser_height=None, start_time=None):
    """Save window and browser settings to config file (nested structure)

    Args:
        x (int, optional): Main window x position
        y (int, optional): Main window y position
        width (int, optional): Main window width
        height (int, optional): Main window height
        headless (bool, optional): Browser headless mode
        screenshot_viewer (bool, optional): Screenshot viewer enabled
        domain_name (str, optional): Domain name for user URLs (e.g., 'localhost' or 'pricewatcher.com')
        port (int, optional): Port number for the web server (e.g., 8080)
        browser_x (int, optional): Browser window x position
        browser_y (int, optional): Browser window y position
        browser_width (int, optional): Browser window width
        browser_height (int, optional): Browser window height
        start_time (str, optional): ISO format start time for uptime calculation

    Note:
        Only provided values will be updated. Existing values are preserved.
        Settings are stored in nested structure matching get_settings() format.
    """
    settings_file = "config/watcher_settings.json"
    os.makedirs("config", exist_ok=True)

    # Load existing settings (use get_settings to ensure nested structure)
    settings = get_settings()

    # Update window position at top level
    if any(v is not None for v in [x, y, width, height]):
        if 'window_position' not in settings:
            settings['window_position'] = {}
        if x is not None:
            settings['window_position']['x'] = x
        if y is not None:
            settings['window_position']['y'] = y
        if width is not None:
            settings['window_position']['width'] = width
        if height is not None:
            settings['window_position']['height'] = height

    # Update system settings if provided (system section)
    if start_time is not None:
        if 'system' not in settings:
            settings['system'] = {}
        settings['system']['start_time'] = start_time

    # Save updated settings
    try:
        with open(settings_file, 'w') as f:
            json.dump(settings, f, indent=2)
        logger.debug(f"Settings saved: {settings}")
    except Exception as e:
        logger.error(f"Failed to save settings: {e}")


def get_settings():
    """Get window and audio settings from config file

    Returns:
        dict: Settings dictionary with sections:
            - audio: watch_folder, model_size, max_file_size_mb
            - window_position: x, y, width, height
            - system: start_time
    """
    settings_file = "config/watcher_settings.json"

    # Default settings for watcher_settings.json
    defaults = {
        'audio': {
            'watch_folder': '',
            'model_size': 'medium',
            'max_file_size_mb': 100
        },
        'window_position': {
            'x': 100,
            'y': 100,
            'width': 800,
            'height': 600
        },
        'system': {
            'start_time': None
        }
    }
    
    try:
        if os.path.exists(settings_file):
            with open(settings_file, 'r') as f:
                content = f.read().strip()
                if content:
                    loaded_settings = json.loads(content)
                    
                    # Check if this is old flat format or new nested format
                    is_old_format = 'domain_name' in loaded_settings and 'server' not in loaded_settings
                    
                    if is_old_format:
                        # Migrate from flat to nested structure
                        logger.info("Migrating settings from flat to nested structure")
                        settings = migrate_flat_to_nested_settings(loaded_settings, defaults)
                        settings_changed = True
                    else:
                        # Use nested structure, ensure all sections exist
                        settings = ensure_nested_settings(loaded_settings, defaults)
                        settings_changed = 'migrated' in settings
                        if settings_changed:
                            del settings['migrated']
                    
                    # Only write back if we actually migrated or added missing defaults
                    if settings_changed:
                        try:
                            with open(settings_file, 'w') as f:
                                json.dump(settings, f, indent=2)
                            logger.info("Settings file updated with new structure or missing defaults")
                        except Exception as write_error:
                            logger.warning(f"Could not write updated settings: {write_error}")
                    
                    return settings
    except Exception as e:
        logger.warning(f"Could not load settings: {e}")
    
    # If file doesn't exist or there was an error, create it with defaults
    try:
        os.makedirs("config", exist_ok=True)
        with open(settings_file, 'w') as f:
            json.dump(defaults, f, indent=2)
        logger.info(f"Created new settings file with defaults: {settings_file}")
    except Exception as e:
        logger.error(f"Failed to create settings file: {e}")
    
    return defaults


def migrate_flat_to_nested_settings(flat_settings, defaults):
    """Migrate old settings structure to new simplified structure"""
    result = copy.deepcopy(defaults)

    # Migrate window_position from browser.window_position if it exists
    if 'browser' in flat_settings and 'window_position' in flat_settings['browser']:
        result['window_position'] = flat_settings['browser']['window_position']

    # Migrate audio settings if they exist
    if 'audio' in flat_settings:
        result['audio'] = flat_settings['audio']

    # Migrate system settings if they exist
    if 'system' in flat_settings:
        result['system'] = flat_settings['system']

    return result


def ensure_nested_settings(settings, defaults):
    """Ensure all sections and keys exist in settings, using defaults"""
    result = copy.deepcopy(settings)
    changed = False

    # Remove old unused sections
    old_sections = ['server', 'browser', 'ai', 'ai_error', 'monitoring', 'ui']
    for section in old_sections:
        if section in result:
            # Migrate window_position from browser if needed
            if section == 'browser' and 'window_position' in result[section]:
                if 'window_position' not in result:
                    result['window_position'] = result[section]['window_position']
            del result[section]
            changed = True

    # Ensure all default sections exist
    for section, section_defaults in defaults.items():
        if section not in result:
            result[section] = copy.deepcopy(section_defaults)
            changed = True
        elif isinstance(section_defaults, dict):
            for key, default_value in section_defaults.items():
                if key not in result[section]:
                    result[section][key] = default_value
                    changed = True

    if changed:
        result['migrated'] = True

    return result


def get_domain_name():
    """Get the configured domain name for user URLs
    
    Returns:
        str: Domain name (e.g., 'localhost' or 'pricewatcher.com')
    """
    settings = get_settings()
    return settings['server'].get('domain_name', 'localhost')


def get_port():
    """Get the configured port number for the web server
    
    Returns:
        int: Port number (default: 8080)
    """
    settings = get_settings()
    return settings['server'].get('port', 8080)


def get_full_domain():
    """Get the full domain with port for constructing URLs
    
    Returns:
        str: Full domain with port (e.g., 'localhost:8080' or 'pricewatcher.com:80')
    """
    domain = get_domain_name()
    port = get_port()
    return f"{domain}:{port}"


def get_ssl_cert():
    """Get the configured SSL certificate file path
    
    Returns:
        str or None: Path to SSL certificate file, or None if not configured
    """
    settings = get_settings()
    return settings['server'].get('ssl_cert')


def get_ssl_key():
    """Get the configured SSL private key file path
    
    Returns:
        str or None: Path to SSL private key file, or None if not configured
    """
    settings = get_settings()
    return settings['server'].get('ssl_key')


def get_protocol():
    """Get the protocol (http or https) based on SSL configuration
    
    Returns:
        str: 'https' if SSL certificates are configured, 'http' otherwise
    """
    ssl_cert = get_ssl_cert()
    ssl_key = get_ssl_key()
    return 'https' if ssl_cert and ssl_key else 'http'


def save_website_settings(x=None, y=None, width=None, height=None, intervals=None, default_interval=None, start_time=None):
    """Save website window position and size to config file
    
    Args:
        x (int, optional): Window x position
        y (int, optional): Window y position
        width (int, optional): Window width
        height (int, optional): Window height
        intervals (list, optional): List of interval dicts with 'minutes' and 'label' keys
        default_interval (int, optional): Default interval in minutes
        start_time (str, optional): ISO format start time for uptime calculation
        
    Note:
        Only provided values will be updated. Existing values are preserved.
        This uses a separate config file (website_settings.json) from the main
        watcher app to keep settings independent.
    """
    settings_file = "config/website_settings.json"
    os.makedirs("config", exist_ok=True)
    
    # Load existing settings
    settings = {}
    if os.path.exists(settings_file):
        try:
            with open(settings_file, 'r') as f:
                content = f.read().strip()
                if content:
                    settings = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Invalid JSON in website settings file, starting fresh")
            settings = {}
    
    # Update window position if provided
    if any(v is not None for v in [x, y, width, height]):
        if 'window_position' not in settings:
            settings['window_position'] = {}
        if x is not None:
            settings['window_position']['x'] = x
        if y is not None:
            settings['window_position']['y'] = y
        if width is not None:
            settings['window_position']['width'] = width
        if height is not None:
            settings['window_position']['height'] = height
    
    # Update intervals if provided
    if intervals is not None:
        settings['update_intervals'] = intervals
    
    # Update default interval if provided
    if default_interval is not None:
        settings['default_interval'] = default_interval
    
    # Update start time if provided
    if start_time is not None:
        settings['start_time'] = start_time
    
    # Save updated settings
    try:
        with open(settings_file, 'w') as f:
            json.dump(settings, f, indent=2)
        
        # Log what was saved
        saved_items = []
        if any(v is not None for v in [x, y, width, height]):
            saved_items.append(f"window position ({width}x{height} at {x},{y})")
        if intervals is not None:
            saved_items.append(f"{len(intervals)} intervals")
        if default_interval is not None:
            saved_items.append(f"default interval: {default_interval}min")
        if start_time is not None:
            saved_items.append(f"start time: {start_time}")
        
        if saved_items:
            logger.debug(f"Saved to {settings_file}: {', '.join(saved_items)}")
    except Exception as e:
        logger.error(f"Failed to save website settings: {e}")


def get_website_settings():
    """Get website window position and size from config file

    Returns:
        dict: Settings dictionary with keys:
            - window_position: dict with x, y, width, height (defaults: x=100, y=100, width=800, height=600)
            - server: dict with domain_name, port, ssl_cert, ssl_key
            - start_time: ISO format timestamp of when the application started
    """
    settings_file = "config/website_settings.json"

    # Default settings for website_settings.json
    defaults = {
        'window_position': {
            'x': 100,
            'y': 100,
            'width': 800,
            'height': 600
        },
        'server': {
            'domain_name': 'localhost',
            'port': 8081,
            'ssl_cert': None,
            'ssl_key': None
        }
    }
    
    try:
        if os.path.exists(settings_file):
            with open(settings_file, 'r') as f:
                content = f.read().strip()
                if content:
                    settings = json.loads(content)
                    needs_save = False
                    
                    # Merge with defaults to ensure all keys exist
                    for section, section_defaults in defaults.items():
                        if section not in settings:
                            settings[section] = section_defaults
                            needs_save = True
                        elif isinstance(section_defaults, dict):
                            for key in section_defaults:
                                if key not in settings[section]:
                                    settings[section][key] = section_defaults[key]
                                    needs_save = True
                    
                    # Save back if we added any defaults
                    if needs_save:
                        try:
                            with open(settings_file, 'w') as f:
                                json.dump(settings, f, indent=2)
                            logger.info(f"Updated website settings file with new defaults")
                        except Exception as e:
                            logger.error(f"Failed to update website settings file: {e}")
                    
                    return settings
    except Exception as e:
        logger.warning(f"Could not load website settings: {e}")
    
    # If file doesn't exist or there was an error, create it with defaults
    try:
        os.makedirs("config", exist_ok=True)
        with open(settings_file, 'w') as f:
            json.dump(defaults, f, indent=2)
        logger.info(f"Created new website settings file with defaults: {settings_file}")
    except Exception as e:
        logger.error(f"Failed to create website settings file: {e}")
    
    return defaults


def get_check_icon():
    """Create a green check icon
    
    Returns:
        QIcon: A white checkmark icon
    """
    from PIL import Image, ImageDraw
    from PyQt5.QtGui import QIcon, QPixmap
    import io
    
    # Create a new image with transparent background
    size = 24
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Draw green checkmark
    color = (255, 255, 255, 255)  # White checkmark
    width = 3
    
    # Checkmark coordinates
    draw.line([(6, 12), (10, 18)], fill=color, width=width)
    draw.line([(10, 18), (18, 6)], fill=color, width=width)
    
    # Convert to QIcon
    buffer = io.BytesIO()
    img.save(buffer, "PNG")
    buffer.seek(0)
    pixmap = QPixmap()
    pixmap.loadFromData(buffer.getvalue())
    return QIcon(pixmap)


def get_x_icon():
    """Create a red X icon

    Returns:
        QIcon: A white X icon
    """
    from PIL import Image, ImageDraw
    from PyQt5.QtGui import QIcon, QPixmap
    import io

    # Create a new image with transparent background
    size = 24
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw white X
    color = (255, 255, 255, 255)  # White X
    width = 3

    # X coordinates
    draw.line([(6, 6), (18, 18)], fill=color, width=width)
    draw.line([(18, 6), (6, 18)], fill=color, width=width)

    # Convert to QIcon
    buffer = io.BytesIO()
    img.save(buffer, "PNG")
    buffer.seek(0)
    pixmap = QPixmap()
    pixmap.loadFromData(buffer.getvalue())
    return QIcon(pixmap)


# ============================================================================
# WEBSITE SERVER SETTINGS FUNCTIONS
# ============================================================================

def get_website_server_settings():
    """Get the server settings from website_settings.json

    Returns:
        dict: Server settings with keys: domain_name, port, ssl_cert, ssl_key
    """
    settings = get_website_settings()
    return settings.get('server', {
        'domain_name': 'localhost',
        'port': 8081,
        'ssl_cert': None,
        'ssl_key': None
    })


def get_website_port():
    """Get the configured port number for the website server

    Returns:
        int: Port number (default: 8081)
    """
    server_settings = get_website_server_settings()
    return server_settings.get('port', 8081)


def get_website_domain():
    """Get the configured domain name for the website server

    Returns:
        str: Domain name (e.g., 'localhost' or 'example.com')
    """
    server_settings = get_website_server_settings()
    return server_settings.get('domain_name', 'localhost')


def get_website_ssl_cert():
    """Get the configured SSL certificate file path for the website server

    Returns:
        str or None: Path to SSL certificate file, or None if not configured
    """
    server_settings = get_website_server_settings()
    return server_settings.get('ssl_cert')


def get_website_ssl_key():
    """Get the configured SSL private key file path for the website server

    Returns:
        str or None: Path to SSL private key file, or None if not configured
    """
    server_settings = get_website_server_settings()
    return server_settings.get('ssl_key')


def get_website_protocol():
    """Get the protocol (http or https) based on SSL configuration for the website server

    Returns:
        str: 'https' if SSL certificates are configured, 'http' otherwise
    """
    ssl_cert = get_website_ssl_cert()
    ssl_key = get_website_ssl_key()
    return 'https' if ssl_cert and ssl_key else 'http'


def get_website_full_domain():
    """Get the full domain with port for the website server

    Returns:
        str: Full domain with port (e.g., 'localhost:8081')
    """
    domain = get_website_domain()
    port = get_website_port()
    return f"{domain}:{port}"
