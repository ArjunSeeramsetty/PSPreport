#!/usr/bin/env python3
"""
Setup script for building the customized my_llama3 model for PDF table parsing.
This script helps you create and configure the optimized LLM model.
"""

import subprocess
import sys
import os
import requests
import time

def check_ollama_installed():
    """Check if Ollama is installed and accessible."""
    try:
        result = subprocess.run(['ollama', '--version'], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ Ollama is installed: {result.stdout.strip()}")
            return True
        else:
            print("❌ Ollama is not properly installed")
            return False
    except FileNotFoundError:
        print("❌ Ollama is not installed. Please install it from https://ollama.com/")
        return False

def check_ollama_server():
    """Check if Ollama server is running."""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            print("✅ Ollama server is running")
            return True
        else:
            print("❌ Ollama server is not responding properly")
            return False
    except requests.ConnectionError:
        print("❌ Ollama server is not running. Please start it with 'ollama serve'")
        return False

def pull_base_model():
    """Pull the base llama3 model."""
    print("📥 Pulling base llama3 model...")
    try:
        result = subprocess.run(['ollama', 'pull', 'llama3'], capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ Base llama3 model pulled successfully")
            return True
        else:
            print(f"❌ Failed to pull base model: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ Error pulling base model: {e}")
        return False

def build_custom_model():
    """Build the custom my_llama3 model using the Modelfile."""
    print("🔨 Building custom my_llama3 model...")
    try:
        # Check if Modelfile.txt exists
        if not os.path.exists('Modelfile.txt'):
            print("❌ Modelfile.txt not found. Please ensure it exists in the current directory.")
            return False
        
        result = subprocess.run(['ollama', 'create', 'my_llama3', '-f', 'Modelfile.txt'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ Custom my_llama3 model built successfully")
            return True
        else:
            print(f"❌ Failed to build custom model: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ Error building custom model: {e}")
        return False

def test_custom_model():
    """Test the custom model with a simple prompt."""
    print("🧪 Testing custom model...")
    try:
        test_prompt = {
            "model": "my_llama3",
            "prompt": "Parse this table data into JSON: State: Maharashtra, Max Demand: 25000 MW, Energy Met: 500 MU",
            "stream": False,
            "format": "json"
        }
        
        response = requests.post("http://localhost:11434/api/generate", 
                               json=test_prompt, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Custom model is working correctly")
            print(f"📝 Test response: {result.get('response', 'No response')[:100]}...")
            return True
        else:
            print(f"❌ Model test failed with status code: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error testing custom model: {e}")
        return False

def list_models():
    """List all available models."""
    print("📋 Available models:")
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get('models', [])
            for model in models:
                print(f"  - {model['name']} (v{model.get('modified_at', 'unknown')})")
        else:
            print("❌ Failed to list models")
    except Exception as e:
        print(f"❌ Error listing models: {e}")

def main():
    """Main setup function."""
    print("🚀 Setting up customized my_llama3 model for PDF table parsing")
    print("=" * 60)
    
    # Check prerequisites
    if not check_ollama_installed():
        sys.exit(1)
    
    if not check_ollama_server():
        print("\n💡 To start Ollama server, run: ollama serve")
        sys.exit(1)
    
    # Pull base model
    if not pull_base_model():
        sys.exit(1)
    
    # Build custom model
    if not build_custom_model():
        sys.exit(1)
    
    # Test custom model
    if not test_custom_model():
        print("⚠️  Custom model test failed, but you can still try using it")
    
    # List all models
    print("\n" + "=" * 60)
    list_models()
    
    print("\n🎉 Setup complete!")
    print("You can now run your PDF processing script with the custom model.")
    print("The model 'my_llama3' is optimized for:")
    print("  - PDF table parsing")
    print("  - JSON generation")
    print("  - NLDC PSP report processing")
    print("  - Power system data extraction")

if __name__ == "__main__":
    main() 