# PDF to Neo4j Graph Builder - Hybrid LLM/Fallback Approach

This project provides a robust solution for extracting structured data from NLDC (National Load Dispatch Centre) Daily PSP (Power System Performance) reports and building interconnected Neo4j graphs. It uses a hybrid approach combining intelligent LLM parsing with reliable fallback methods.

## 🚀 Features

- **Hybrid Processing**: Primary LLM-based parsing with automatic fallback to coordinate-based extraction
- **Custom LLM Model**: Optimized `my_llama3` model specifically tuned for PDF table parsing
- **Robust Error Handling**: Graceful degradation when services are unavailable
- **Complete Graph Building**: Extracts all major data types from NLDC reports
- **Flexible Data Upload**: Handles various data formats and missing fields gracefully

## 📋 Prerequisites

### 1. Neo4j Database
- Download and install [Neo4j Desktop](https://neo4j.com/download/)
- Create a new DBMS and start it
- Default credentials: `neo4j` / `powerflow`

### 2. Ollama LLM Server
- Download and install [Ollama](https://ollama.com/)
- Ensure the server is running (`ollama serve`)

### 3. Python Dependencies
```bash
pip install neo4j pandas pdfplumber requests tabula-py PyPDF2
```

## 🛠️ Setup Instructions

### Step 1: Build Custom LLM Model
Run the setup script to create the optimized model:

```bash
python setup_custom_model.py
```

This script will:
- Check if Ollama is installed and running
- Pull the base llama3 model
- Build the custom `my_llama3` model using `Modelfile.txt`
- Test the model functionality

### Step 2: Configure the Script
Update the configuration in `sample.py`:

```python
# --- CONFIGURATION ---
NEO4J_CONFIG = {
    "uri": "neo4j://localhost:7687",
    "user": "neo4j",
    "password": "powerflow"  # Change to your password
}
PDF_PATH = "./sample input/19.04.25_NLDC_PSP.pdf"  # Update path
```

### Step 3: Run the Script
```bash
python sample.py
```

## 📊 Data Extraction Capabilities

The system extracts the following data types from NLDC PSP reports:

### 1. State Power Position
- **Data**: State-wise power demand and supply metrics
- **Schema**: `{"region": "string", "state": "string", "max_demand_mw": "float", "energy_met_mu": "float", "energy_shortage_mu": "float"}`
- **Graph**: State → Region relationships with metrics

### 2. Source-wise Generation
- **Data**: Power generation by source and region
- **Schema**: `{"source": "string", "region": "string", "generation_mu": "float"}`
- **Graph**: Region → GenerationSource relationships

### 3. Generation Outage
- **Data**: Power plant outages by sector
- **Schema**: `{"sector": "string", "outage_mw": "float"}`
- **Graph**: Report → Outage relationships

### 4. Inter-Regional Exchanges
- **Data**: Power exchanges between regions via transmission lines
- **Schema**: `{"source_region": "string", "target_region": "string", "power_line": "string", "voltage": "string", "net_mu": "float"}`
- **Graph**: Region → Region relationships via PowerLine

### 5. Transnational Exchanges
- **Data**: International power exchanges
- **Schema**: `{"country": "string", "actual_mu": "float", "day_peak_mw": "float"}`
- **Graph**: Country → India relationships

## 🔧 Custom LLM Model Configuration

The `Modelfile.txt` contains optimized settings for PDF table parsing:

### Key Optimizations:
- **Low Temperature (0.1)**: Ensures consistent JSON output
- **Specialized System Prompt**: Domain knowledge for power systems
- **JSON Format Enforcement**: Built-in JSON generation capabilities
- **Context Window**: 8192 tokens for handling large tables
- **Stop Tokens**: Prevents extra formatting in responses

### Model Features:
- Domain-specific knowledge of Indian power systems
- Optimized for table structure recognition
- Robust error handling for unclear data
- Consistent JSON schema compliance

## 🛡️ Error Handling & Fallback

### LLM Failures
- **Timeout Handling**: 2-minute timeout with automatic fallback
- **Connection Errors**: Graceful degradation when Ollama is unavailable
- **Invalid Responses**: Fallback to coordinate-based parsing

### Fallback Parsing
- **Precise Coordinates**: Uses pdfplumber with exact table coordinates
- **Robust Extraction**: Handles various table formats and layouts
- **Data Validation**: Ensures extracted values are reasonable

### Neo4j Issues
- **Connection Testing**: Validates database connectivity before upload
- **Graceful Degradation**: Continues processing even if upload fails
- **Detailed Error Messages**: Clear troubleshooting instructions

## 📈 Performance Optimizations

### LLM Optimizations:
- **Reduced Temperature**: More deterministic outputs
- **Specialized Prompts**: Domain-specific instructions
- **JSON Format**: Direct JSON generation without parsing

### Processing Optimizations:
- **Hybrid Approach**: Best of both LLM and rule-based methods
- **Parallel Processing**: Independent table extraction
- **Memory Efficient**: Processes tables individually

## 🔍 Troubleshooting

### Common Issues:

1. **Ollama Not Running**
   ```bash
   ollama serve
   ```

2. **Model Not Found**
   ```bash
   python setup_custom_model.py
   ```

3. **Neo4j Connection Failed**
   - Check if Neo4j Desktop is running
   - Verify credentials in configuration
   - Ensure port 7687 is accessible

4. **PDF Path Issues**
   - Verify PDF file exists
   - Check file permissions
   - Update PDF_PATH in configuration

### Debug Information:
The script provides detailed logging for:
- LLM processing status
- Fallback parsing results
- Neo4j upload progress
- Error details and suggestions

## 📁 File Structure

```
├── sample.py                 # Main processing script
├── Modelfile.txt            # Custom LLM configuration
├── setup_custom_model.py    # Model setup script
├── README.md               # This file
└── sample input/           # PDF files directory
    └── 19.04.25_NLDC_PSP.pdf
```

## 🤝 Contributing

To improve the system:

1. **Enhance Fallback Parsing**: Add more table type handlers
2. **Optimize LLM Prompts**: Improve prompt engineering for better results
3. **Add Data Validation**: Implement more robust data quality checks
4. **Extend Graph Schema**: Add new relationship types and properties

## 📄 License

This project is for research and educational purposes. The custom LLM model is derived from Meta's Llama 3 and is subject to Meta's license terms.

## 🆘 Support

For issues and questions:
1. Check the troubleshooting section
2. Review the detailed error messages
3. Verify all prerequisites are met
4. Test with the setup script first 
