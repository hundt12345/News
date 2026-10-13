# News Aggregator

A local news aggregator that automatically discovers and aggregates news sources for a given city or district.

## Features

- Enter a city/quarter and get automatic discovery of local news sources
- Weather information (optional, requires OpenWeatherMap API key)
- Reddit integration for city-specific subreddits and searches
- Simple web interface with stream and summary views

## Local Development

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py
```

Then open http://localhost:5000 in your browser.

## Deployment to Render

### Option 1: Using Render Blueprint (recommended)

1. Create a new Web Service on Render
2. Connect your GitHub repository
3. Render will automatically detect the `render.yaml` file
4. Set the following environment variables:
   - `PORT`: 10000 (or any port you prefer)
   - `OWM_API_KEY`: Your OpenWeatherMap API key (optional)
5. Deploy!

### Option 2: Manual Configuration

1. Create a new Web Service on Render
2. Set the Build Command to: `pip install -r requirements.txt`
3. Set the Start Command to: `python app.py`
4. Set the following environment variables:
   - `PORT`: 10000
   - `OWM_API_KEY`: Your OpenWeatherMap API key (optional)
5. Deploy!

## Configuration

### Environment Variables

- `PORT`: The port the app should listen on (default: 5000)
- `OWM_API_KEY`: OpenWeatherMap API key for weather information (optional)

### Adding News Sources

Edit `crawler.py` and add entries to the `SOURCES` dictionary:
```python
SOURCES = {
    "Source Name": (base_url, rss_url),
    # If rss_url is provided, it will be used directly
    # If rss_url is None, the base_url will be crawled
}
```

Reddit sources are automatically added based on the city name.

## Project Structure

- `app.py`: Flask web application
- `crawler.py`: News crawling logic with source discovery
- `templates/index.html`: Web interface template
- `requirements.txt`: Python dependencies
- `render.yaml`: Render deployment configuration
