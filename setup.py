"""Setup script for Document Wizard."""

from setuptools import setup, find_packages

setup(
    name="documentwizard",
    version="0.1.0",
    description="A floating chatbot that reads your open documents",
    packages=find_packages(),
    python_requires=">=3.9",
    entry_points={
        "console_scripts": [
            "screencompanion=screencompanion.app:main",
        ],
    },
)
