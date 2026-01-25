"""
TradePy Execution Test Script
Validates that all TradePy modules can be imported and executed without error
"""
import sys
import traceback
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_module_imports():
    """Test importing all critical TradePy modules"""
    print("Testing module imports...")

    modules_to_test = [
        # Core modules
        ("core.data.validator", "DataValidator"),
        ("core.validation.risk_validation", "RiskValidator"),
        ("core.validation.risk_validation", "MaxDrawdownValidator"),
        ("core.validation.risk_validation", "RiskPerTradeValidator"),
        ("core.validation.risk_validation", "PositionSizeValidator"),
        ("core.strategy.trend_following_strategy", "TrendFollowingStrategy"),
        ("core.strategy.base", "Strategy"),
        ("core.strategy.signal", "SignalType"),
        ("core.risk.manager", "RiskManager"),
        ("core.risk.rules", "RiskRule"),
        ("utils.logger", "Logger"),
        ("utils.time", "get_current_time"),
        ("utils.helpers", "calculate_percentage_change"),

        # Backtest modules
        ("backtest.engine", "BacktestEngine"),
        ("backtest.analysis", "BacktestAnalyzer"),
        ("backtest.benchmark", "Benchmark"),
        ("backtest.benchmark", "BenchmarkAnalyzer"),
        ("backtest.walk_forward", "WalkForwardAnalyzer"),
        ("backtest.walk_forward", "WindowConfig"),
        ("backtest.walk_forward", "WalkForwardReport"),

        # Live modules
        ("live.kill_switch", "KillSwitch"),
        ("live.kill_switch", "GlobalKillSwitch"),
        ("live.runner", "LiveRunner"),
        ("live.watcher", "Watcher"),
        ("live.notifier", "Notifier"),

        # Config
        ("config.config", "load_config")
    ]

    failed_imports = []
    successful_imports = []

    for module_path, class_name in modules_to_test:
        try:
            module = __import__(module_path, fromlist=[class_name])
            klass = getattr(module, class_name)
            print(f"OK Successfully imported: {module_path}.{class_name}")
            successful_imports.append(f"{module_path}.{class_name}")
        except ImportError as e:
            print(f"ERROR Failed to import: {module_path}.{class_name} - {e}")
            failed_imports.append((f"{module_path}.{class_name}", str(e)))
        except AttributeError as e:
            print(f"ERROR Attribute error: {module_path}.{class_name} - {e}")
            failed_imports.append((f"{module_path}.{class_name}", str(e)))
        except Exception as e:
            print(f"ERROR Error importing: {module_path}.{class_name} - {e}")
            failed_imports.append((f"{module_path}.{class_name}", str(e)))

    print(f"\\nImport Summary: {len(successful_imports)} successful, {len(failed_imports)} failed")
    assert len(failed_imports) == 0, f"Failed imports: {failed_imports}"
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
        assert status['active'] is not None, "KillSwitch status should have 'active' field"

        # Test risk validators
        from core.validation.risk_validation import MaxDrawdownValidator, RiskPerTradeValidator
        md_validator = MaxDrawdownValidator()
        rt_validator = RiskPerTradeValidator()
        print("✓ Risk validators instantiated successfully")

        # Test strategy
        from core.strategy.trend_following_strategy import TrendFollowingStrategy
        strategy = TrendFollowingStrategy()
        print(f"✓ Strategy instantiated: {strategy.get_name()}")
        assert strategy.get_name() is not None, "Strategy should have a name"

        return True
    except Exception as e:
        print(f"✗ Error testing basic functionality: {e}")
        traceback.print_exc()
        assert False, f"Basic functionality test failed: {e}"
        return False

def test_walk_forward_concept():
    """Test walk-forward concepts without full execution"""
    print("\\nTesting walk-forward concepts...")

    try:
        from backtest.walk_forward import WindowConfig
        config = WindowConfig()
        print(f"✓ WindowConfig created: {config.in_sample_period} / {config.out_of_sample_period}")
        assert config.in_sample_period is not None, "WindowConfig should have in_sample_period"
        assert config.out_of_sample_period is not None, "WindowConfig should have out_of_sample_period"

        from backtest.walk_forward import WalkForwardAnalyzer
        # Note: We won't instantiate with actual strategy since it may depend on external libs
        print("✓ WalkForwardAnalyzer class loaded successfully")

        return True
    except Exception as e:
        print(f"✗ Error testing walk-forward concepts: {e}")
        traceback.print_exc()
        assert False, f"Walk-forward concept test failed: {e}"
        return False

def test_config_loading():
    """Test configuration loading"""
    print("\\nTesting configuration loading...")

    try:
        from config.config import load_config
        import tempfile
        import yaml

        # Create a temporary config file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
            test_config = {
                'mode': 'backtest',
                'exchange': 'binance',
                'timeframe': '1h',
                'initial_capital': 10000
            }
            yaml.dump(test_config, tmp)
            tmp_path = tmp.name

        # Load the config
        config = load_config(tmp_path)
        print(f"✓ Config loaded: {config['mode']}, capital: ${config['initial_capital']}")
        assert config['mode'] == 'backtest', "Config should have correct mode"
        assert config['initial_capital'] == 10000, "Config should have correct capital"

        # Cleanup
        import os
        os.unlink(tmp_path)

        return True
    except Exception as e:
        print(f"✗ Error testing config loading: {e}")
        traceback.print_exc()
        assert False, f"Config loading test failed: {e}"
        return False

def main():
    """Main execution function"""
    print("=" * 60)
    print("TRADEPY EXECUTION VALIDATION")
    print("=" * 60)
    
    print("Step 1: Testing module imports")
    failed_imports = test_module_imports()
    
    print("\\nStep 2: Testing basic functionality")
    func_success = test_basic_functionality()
    
    print("\\nStep 3: Testing walk-forward concepts")
    wf_success = test_walk_forward_concept()
    
    print("\\nStep 4: Testing configuration loading")
    config_success = test_config_loading()
    
    print("\\n" + "=" * 60)
    print("EXECUTION VALIDATION SUMMARY")
    print("=" * 60)

    if failed_imports:
        print(f"ERROR {len(failed_imports)} modules failed to import:")
        for module, error in failed_imports:
            print(f"  - {module}: {error}")

    if not func_success:
        print("ERROR Basic functionality tests failed")

    if not wf_success:
        print("ERROR Walk-forward concept tests failed")

    if not config_success:
        print("ERROR Configuration loading tests failed")

    all_passed = len(failed_imports) == 0 and func_success and wf_success and config_success

    if all_passed:
        print("\\nSUCCESS ALL VALIDATIONS PASSED!")
        print("TradePy framework can be executed without errors")
    else:
        print("\\nFAILURE SOME VALIDATIONS FAILED!")
        print("Review the errors above")
    
    return all_passed

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)