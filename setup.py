from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()


def _load_requirements(path: str):
    requirements = []
    with open(path, "r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if " #" in line:
                line = line.split(" #", 1)[0].strip()
            requirements.append(line)
    return requirements


requirements = _load_requirements("requirements.txt")

setup(
    name="tradepy",
    version="0.1.0",
    author="TradePy Development Team",
    author_email="contact@tradepy.ai",
    description="A robust trading bot framework with clean architecture",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/tradepy",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: Financial and Insurance Industry",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.8",
    install_requires=requirements,
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-cov>=4.0",
            "ruff>=0.6.0",
            "black>=21.0",
            "flake8>=3.8",
        ],
        "research": [
            "backtesting>=0.3.3",
            "optuna>=3.0.0",
            "ta>=0.11.0",
            "arch>=5.3.0",
            "plotly>=5.0.0",
        ],
        "crypto": [
            "ccxt>=4.0.0",
        ],
        "backtest": [
            "plotly>=5.0.0",
        ]
    }
)
