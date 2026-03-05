"""
TradePy Environment Setup Script
Creates an isolated Python environment for TradePy execution
"""
import os
import sys
import subprocess
import platform
from pathlib import Path
import shutil

def create_minimal_requirements():
    """Create minimal requirements file for TradePy"""
    req_content = """# Minimal requirements for TradePy execution
pandas>=1.5.0
numpy>=1.23.0
matplotlib>=3.5.0,<3.8.0
seaborn>=0.12.0
pyyaml>=6.0,<7.0
python-dotenv>=1.0.0
MetaTrader5>=5.0.45
tenacity>=8.2.0
pydantic>=2.0.0,<3.0.0
"""
    
    with open("minimal_requirements.txt", "w", encoding="utf-8") as f:
        f.write(req_content)
    
    print("Created minimal_requirements.txt with compatible dependencies")

def create_venv():
    """Create virtual environment"""
    print("Creating isolated Python environment for TradePy...")
    
    venv_name = "tradepy_env"
    venv_path = Path(venv_name)
    
    # Remove existing venv if needed
    if venv_path.exists():
        print(f"Removing existing {venv_name}...")
        shutil.rmtree(venv_path)
    
    # Create virtual environment
    cmd = [sys.executable, "-m", "venv", str(venv_path)]
    print(f"Executing: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error creating virtual environment: {result.stderr}")
        return None
    
    # Determine activation script path
    if platform.system() == "Windows":
        pip_path = str(venv_path / "Scripts" / "pip.exe")
        python_path = str(venv_path / "Scripts" / "python.exe")
    else:
        pip_path = str(venv_path / "bin" / "pip")
        python_path = str(venv_path / "bin" / "python")
    
    print(f"Virtual environment created: {venv_path}")
    return venv_path, python_path, pip_path

def install_dependencies(venv_path, pip_path):
    """Install dependencies in the virtual environment"""
    print("Installing minimal dependencies...")
    
    # Upgrade pip first
    cmd = [pip_path, "install", "--upgrade", "pip"]
    print(f"Upgrading pip...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Pip upgrade failed: {result.stderr}")
        return False
    
    # Install minimal requirements
    cmd = [pip_path, "install", "-r", "minimal_requirements.txt"]
    print("Installing requirements...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Requirements installation failed: {result.stderr}")
        return False
    
    # Install TradePy in development mode
    cmd = [pip_path, "install", "-e", "."]
    print("Installing TradePy in development mode...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"TradePy installation failed: {result.stderr}")
        return False
    
    print("Dependencies installed successfully")
    return True

def create_test_execution_script():
    """Create a test script to validate all modules"""
    script_content = '''"""
TradePy Execution Validation Script
Validates that all TradePy modules can be imported and executed without error
"""
import sys
import traceback
from pathlib import Path

def test_module_imports():
    """Test importing all critical TradePy modules"""
    print("Testing module imports...")
    
    modules_to_test = [
        # Core modules
        "core.data.validator",
        "core.validation.risk_validation", 
        "core.strategy.trend_following_strategy",
        "core.strategy.base",
        "core.strategy.signal",
        "core.risk.manager",
        "core.risk.rules",
        "utils.logger",
        "utils.time",
        "utils.helpers",
        
        # Backtest modules
        "backtest.engine",
        "backtest.analysis", 
        "backtest.benchmark",
        "backtest.walk_forward",
        "backtest.metrics",
        "backtest.reports",
        
        # Live modules
        "live.kill_switch",
        "live.runner",
        "live.watcher",
        "live.notifier",
        
        # Config
        "config.config"
    ]
    
    failed_imports = []
    successful_imports = []
    
    for module in modules_to_test:
        try:
            # Construct full import path
            full_module_path = f"tradeppy.{module}"  # Using relative import
            __import__(full_module_path)
            print(f"✓ Successfully imported: {module}")
            successful_imports.append(module)
        except ImportError as e:
            print(f"✗ Failed to import: {module} - {e}")
            failed_imports.append((module, str(e)))
        except Exception as e:
            print(f"✗ Error importing: {module} - {e}")
            failed_imports.append((module, str(e)))
    
    print(f"\\nImport Summary: {len(successful_imports)} successful, {len(failed_imports)} failed")
    return failed_imports

def test_basic_functionality():
    """Test basic functionality of key modules"""
    print("\\nTesting basic functionality...")
    
    try:
        # Test data validator
        from core.data.validator import DataValidator
        validator = DataValidator()
        print("✓ DataValidator instantiated successfully")
        
        # Test kill switch
        from live.kill_switch import KillSwitch
        kill_switch = KillSwitch()
        status = kill_switch.get_status()
        print(f"✓ KillSwitch instantiated successfully - Active: {status['active']}")
        
        # Test risk validators
        from core.validation.risk_validation import MaxDrawdownValidator, RiskPerTradeValidator
        md_validator = MaxDrawdownValidator()
        rt_validator = RiskPerTradeValidator()
        print("✓ Risk validators instantiated successfully")
        
        return True
    except Exception as e:
        print(f"✗ Error testing basic functionality: {e}")
        traceback.print_exc()
        return False

def test_walk_forward_concept():
    """Test walk-forward concepts without full execution"""
    print("\\nTesting walk-forward concepts...")
    
    try:
        from backtest.walk_forward import WindowConfig
        config = WindowConfig()
        print(f"✓ WindowConfig created: {config.in_sample_period} / {config.out_of_sample_period}")
        
        return True
    except Exception as e:
        print(f"✗ Error testing walk-forward concepts: {e}")
        traceback.print_exc()
        return False

def main():
    """Main execution function"""
    print("=" * 60)
    print("TRADEPY EXECUTION VALIDATION")
    print("=" * 60)
    
    # Change to the TradePy directory
    project_root = Path(__file__).parent
    import sys
    sys.path.insert(0, str(project_root))
    
    print("Step 1: Testing module imports")
    failed_imports = test_module_imports()
    
    print("\\nStep 2: Testing basic functionality")
    func_success = test_basic_functionality()
    
    print("\\nStep 3: Testing walk-forward concepts")
    wf_success = test_walk_forward_concept()
    
    print("\\n" + "=" * 60)
    print("EXECUTION VALIDATION SUMMARY")
    print("=" * 60)
    
    if failed_imports:
        print(f"✗ {len(failed_imports)} modules failed to import:")
        for module, error in failed_imports:
            print(f"  - {module}: {error}")
    
    if not func_success:
        print("✗ Basic functionality tests failed")
    
    if not wf_success:
        print("✗ Walk-forward concept tests failed")
    
    all_passed = len(failed_imports) == 0 and func_success and wf_success
    
    if all_passed:
        print("\\n🎉 ALL VALIDATIONS PASSED!")
        print("TradePy framework can be executed without errors")
    else:
        print("\\n❌ SOME VALIDATIONS FAILED!")
        print("Review the errors above")
    
    return all_passed

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
'''
    
    with open("test_execution.py", "w", encoding="utf-8") as f:
        f.write(script_content)
    
    print("Created test_execution.py for execution validation")

def main():
    """Main setup function"""
    print("Setting up TradePy execution environment...")
    
    # Create minimal requirements
    create_minimal_requirements()
    
    # Create virtual environment
    result = create_venv()
    if not result:
        print("Failed to create virtual environment")
        return False
    
    venv_path, python_path, pip_path = result
    
    # Install dependencies
    if not install_dependencies(venv_path, pip_path):
        print("Failed to install dependencies")
        return False
    
    # Create test script
    create_test_execution_script()
    
    print("\\nEnvironment setup completed successfully!")
    print(f"Virtual environment: {venv_path}")
    print(f"To activate: {venv_path}\\Scripts\\activate (Windows) or source {venv_path}/bin/activate (Linux/Mac)")
    print(f"To run validation: python test_execution.py")
    
    return True

if __name__ == "__main__":
    success = main()
    if success:
        print("\\nEnvironment setup completed successfully! You can now run: python test_execution.py")
    else:
        print("\\nEnvironment setup failed!")
        sys.exit(1)
