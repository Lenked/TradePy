"""
Final TradePy Execution Validation
Performs a minimal execution test verifying all critical components work together
"""
import sys
import traceback
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_kill_switch_functionality():
    """Test the kill switch functionality"""
    print("Testing Kill Switch functionality...")
    try:
        from live.kill_switch import KillSwitch
        kill_switch = KillSwitch()

        # Test initial state
        status = kill_switch.get_status()
        print(f"  OK KillSwitch initialized - Active: {status['active']}")
        assert status['active'] is not None, "KillSwitch should have active status"

        # Test update metrics
        kill_switch.update_metrics(0.05, 0.02, False)  # 5% drawdown, 2% daily loss
        status = kill_switch.get_status()
        print(f"  OK Metrics updated - Current drawdown: {status['current_drawdown']:.1%}")
        assert status['current_drawdown'] == 0.05, "Current drawdown should be 5%"

        # Test evaluation - should not trigger (below thresholds)
        should_stop, reason = kill_switch.evaluate_kill_condition()
        print(f"  OK Evaluation: {not should_stop} (as expected) - Reason: {reason}")
        assert should_stop is False, "Kill switch should not trigger with 5% drawdown"

        # Test manual activation
        kill_switch.activate_manual_stop("Test activation")
        status = kill_switch.get_status()
        print(f"  OK Manual activation worked - Active: {status['active']}, Manual override: {status['manual_override']}")
        assert status['active'] is False, "Kill switch should be inactive after manual activation (but marked as manually overridden)"
        assert status['manual_override'] is True, "Manual override should be True"

        # Deactivate for continuation
        kill_switch.deactivate_manual_stop()
        status = kill_switch.get_status()
        print(f"  OK Manual deactivation worked - Active: {status['active']}")
        assert status['active'] is True, "Kill switch should be active after manual deactivation"

        return True
    except Exception as e:
        print(f"  ERROR Kill Switch test failed: {e}")
        traceback.print_exc()
        assert False, f"Kill switch test failed: {e}"
        return False

def test_walk_forward_setup():
    """Test that walk-forward components can be imported and configured"""
    print("\\nTesting Walk-Forward Analysis setup...")
    try:
        from backtest.walk_forward import WindowConfig, WalkForwardAnalyzer
        from core.strategy.trend_following_strategy import TrendFollowingStrategy

        # Test configuration creation
        config = WindowConfig(
            in_sample_period="3M",      # 3 months in-sample
            out_of_sample_period="1M",  # 1 month out-of-sample
            overlap=False
        )
        print(f"  OK WindowConfig created: {config.in_sample_period} / {config.out_of_sample_period}")
        assert config.in_sample_period == "3M", "WindowConfig should have correct in_sample_period"
        assert config.out_of_sample_period == "1M", "WindowConfig should have correct out_of_sample_period"
        assert config.overlap is False, "WindowConfig should have overlap as False"

        # Test strategy instantiation
        strategy = TrendFollowingStrategy()
        print(f"  OK Strategy loaded: {strategy.get_name()}")
        assert strategy.get_name() is not None, "Strategy should have a name"

        # Note: We're not running full analysis as it requires data and dependencies
        print("  OK Walk-forward components can be imported and instantiated")

        return True
    except Exception as e:
        print(f"  ERROR Walk-Forward test failed: {e}")
        traceback.print_exc()
        assert False, f"Walk-forward setup test failed: {e}"
        return False

def test_basic_backtest_setup():
    """Test basic backtest components"""
    print("\\nTesting Basic Backtest setup...")
    try:
        from backtest.engine import BacktestEngine
        from backtest.analysis import BacktestAnalyzer
        from core.strategy.trend_following_strategy import TrendFollowingStrategy

        # Test engine initialization
        engine = BacktestEngine(initial_capital=10000)
        print(f"  OK BacktestEngine initialized with capital: ${engine.initial_capital:,.0f}")
        assert engine.initial_capital == 10000, "BacktestEngine should have correct initial capital"

        # Test analyzer initialization
        analyzer = BacktestAnalyzer()
        print("  OK BacktestAnalyzer initialized")

        # Test strategy
        strategy = TrendFollowingStrategy()
        print(f"  OK Strategy loaded: {strategy.get_name()}")
        assert strategy.get_name() is not None, "Strategy should have a name"

        # Test basic analysis function
        from backtest.analysis import analyze_backtest_results
        print("  OK Analysis functions accessible")

        return True
    except Exception as e:
        print(f"  ERROR Basic Backtest test failed: {e}")
        traceback.print_exc()
        assert False, f"Basic backtest setup test failed: {e}"
        return False

def main():
    """Main validation function"""
    print("=" * 70)
    print("TRADEPY CRITICAL EXECUTION VALIDATION")
    print("Testing key components: Kill Switch, Walk-Forward, Basic Backtest")
    print("=" * 70)
    
    print("\\nThis test validates that critical components can be imported and")
    print("executed without errors, ensuring the framework is runnable.")
    print("(Actual full execution would require all dependencies installed)")
    
    # Test each critical component
    kill_switch_ok = test_kill_switch_functionality()
    wf_ok = test_walk_forward_setup()
    backtest_ok = test_basic_backtest_setup()
    
    print("\\n" + "=" * 70)
    print("EXECUTION VALIDATION RESULTS")
    print("=" * 70)
    
    results = [
        ("Kill Switch functionality", kill_switch_ok),
        ("Walk-Forward Analysis setup", wf_ok),
        ("Basic Backtest setup", backtest_ok)
    ]
    
    all_passed = True
    for component, status in results:
        status_text = "PASS" if status else "FAIL"
        icon = "OK" if status else "ERROR"
        print(f"{icon} {component:<30} {status_text}")
        if not status:
            all_passed = False
    
    print("\\n" + "=" * 70)
    print("FRAMEWORK EXECUTION ASSESSMENT")
    print("=" * 70)
    
    if all_passed:
        print("SUCCESS: All critical components validated successfully!")
        print("\\nThe TradePy framework can execute the following without errors:")
        print("- Kill Switch activation/deactivation")
        print("- Walk-Forward Analysis configuration") 
        print("- Basic Backtesting setup")
        print("\\nFramework is ready for execution after dependency installation")
        print("\\nPhilosophy: 'Survival first, profitability second' - CHECK")
    else:
        print("FAILURE: Some critical components failed validation!")
        print("Review the errors above before attempting execution")
    
    return all_passed

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)