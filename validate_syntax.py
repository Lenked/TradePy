"""
TradePy Basic Validation Script
Tests basic syntax and structure without heavy dependencies
"""
import sys
import ast
import os
from pathlib import Path

def validate_syntax(filepath):
    """Validate that a Python file has correct syntax"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        ast.parse(content)  # This will raise an exception if syntax is invalid
        print(f"  OK {filepath} - Syntax valid")
        return True
    except SyntaxError as e:
        print(f"  ERROR {filepath} - Syntax error: {e}")
        return False
    except Exception as e:
        print(f"  ERROR {filepath} - Could not parse: {e}")
        return False

def find_python_files(root_dir):
    """Find all Python files in the directory tree"""
    python_files = []
    for root, dirs, files in os.walk(root_dir):
        # Skip venv directories
        dirs[:] = [d for d in dirs if not d.startswith('venv') and not d.startswith('.') and not d.startswith('tradepy_env')]
        for file in files:
            if file.endswith('.py'):
                python_files.append(os.path.join(root, file))
    return python_files

def main():
    """Main validation function"""
    print("=" * 60)
    print("TRADEPY BASIC VALIDATION")
    print("Checking syntax and basic structure of all Python files")
    print("=" * 60)
    
    project_root = Path(".")
    python_files = find_python_files(project_root)
    
    # Filter to only check TradePy source files
    trade_py_files = [f for f in python_files if 'trade_py' in f.lower() or 
                     'core' in f.lower() or 'backtest' in f.lower() or 
                     'live' in f.lower() or 'utils' in f.lower() or 
                     'config' in f.lower() or f.endswith('main.py') or f.endswith('validate_framework.py')]
    
    print(f"Found {len(trade_py_files)} TradePy Python files to validate")
    
    results = {
        'valid': [],
        'invalid': []
    }
    
    for filepath in trade_py_files:
        if validate_syntax(filepath):
            results['valid'].append(filepath)
        else:
            results['invalid'].append(filepath)
    
    print("\\n" + "=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)
    
    print(f"Valid files: {len(results['valid'])}")
    print(f"Invalid files: {len(results['invalid'])}")
    
    if results['invalid']:
        print("\\nFiles with syntax errors:")
        for filepath in results['invalid']:
            print(f"  - {filepath}")
    
    all_valid = len(results['invalid']) == 0
    
    if all_valid:
        print("\\nSUCCESS: All Python files have valid syntax!")
        print("TradePy can be imported without syntax errors")
        print("\\nNext step: Install dependencies and run full import tests")
    else:
        print("\\nFAILURE: Some files have syntax errors!")
        print("Fix the syntax errors before proceeding")
    
    return all_valid

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)