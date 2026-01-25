#!/usr/bin/env python3
"""
Setup script for TradePy development environment
"""
import os
import sys
import subprocess
import platform
from pathlib import Path

def create_virtual_environment():
    """Create a virtual environment for TradePy"""
    print("Setting up TradePy development environment...")
    
    # Check if Python 3 is available
    if sys.version_info < (3, 8):
        print("Error: Python 3.8 or higher is required")
        return False
    
    # Create virtual environment
    venv_dir = Path("tradepy_env")
    
    if platform.system() == "Windows":
        python_cmd = "python"
        venv_cmd = [python_cmd, "-m", "venv", str(venv_dir)]
        pip_cmd = [str(venv_dir / "Scripts" / "python"), "-m", "pip"]
    else:
        python_cmd = "python3"
        venv_cmd = [python_cmd, "-m", "venv", str(venv_dir)]
        pip_cmd = [str(venv_dir / "bin" / "python"), "-m", "pip"]
    
    print("Creating virtual environment...")
    try:
        subprocess.check_call(venv_cmd)
        print(f"Virtual environment created at {venv_dir}")
    except subprocess.CalledProcessError as e:
        print(f"Error creating virtual environment: {e}")
        return False
    
    # Upgrade pip
    print("Upgrading pip...")
    try:
        subprocess.check_call(pip_cmd + ["install", "--upgrade", "pip"])
    except subprocess.CalledProcessError as e:
        print(f"Error upgrading pip: {e}")
        return False
    
    # Install requirements
    print("Installing requirements...")
    try:
        subprocess.check_call(pip_cmd + ["install", "-r", "requirements.txt"])
        print("Requirements installed successfully")
    except subprocess.CalledProcessError as e:
        print(f"Error installing requirements: {e}")
        return False
    
    # Install the package in development mode
    print("Installing TradePy in development mode...")
    try:
        subprocess.check_call(pip_cmd + ["install", "-e", "."])
        print("TradePy installed successfully")
    except subprocess.CalledProcessError as e:
        print(f"Error installing TradePy: {e}")
        return False
    
    print("\nSetup completed successfully!")
    print("\nTo activate the virtual environment:")
    if platform.system() == "Windows":
        print(f"  {venv_dir / 'Scripts' / 'activate'}")
    else:
        print(f"  source {venv_dir / 'bin' / 'activate'}")
    
    print("\nTo run the validation script:")
    print("  python validate_framework.py")
    
    return True

if __name__ == "__main__":
    success = create_virtual_environment()
    if not success:
        sys.exit(1)