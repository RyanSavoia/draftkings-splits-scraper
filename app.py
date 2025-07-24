import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify
from flask_cors import CORS
import re
import os
from datetime import datetime, timedelta

app = Flask(__name__)

# Add CORS configuration for your domains
CORS(app, origins=[
    "https://thebettinginsider.com",
    "https://www.thebettinginsider.com"
])

# Global variables to store scraped data and timestamp
cached_games_data = []
cache_timestamp = None
CACHE_DURATION_MINUTES = 30  # Cache expires after 30 minutes

def is_cache_expired():
    """Check if cache has expired"""
    global cache_timestamp
    if cache_timestamp is None:
        return True
    
    now = datetime.now()
    cache_age = now - cache_timestamp
    return cache_age > timedelta(minutes=CACHE_DURATION_MINUTES)

def get_cached_or_fresh_data():
    """Get cached data if available and not expired, otherwise scrape fresh data"""
    global cached_games_data, cache_timestamp
    
    if cached_games_data and not is_cache_expired():
        print(f"Using cached data (age: {datetime.now() - cache_timestamp})...")
        return cached_games_data
    else:
        print("Cache expired or empty, scraping fresh data...")
        fresh_data = scrape_betting_splits()
        cached_games_data = fresh_data
        cache_timestamp = datetime.now()
        return fresh_data

def scrape_betting_splits():
    """Scrape betting splits from DraftKings - all active sports for today and tomorrow"""
    base_url = "https://dknetwork.draftkings.com/draftkings-sportsbook-betting-splits/"
   
    # Known sport IDs - get today AND tomorrow for everything (except soccer)
    sport_configs = {
        'all_sports': {'id': 0, 'date_ranges': ['today', 'tomorrow']},
        'mlb': {'id': 84240, 'date_ranges': ['today', 'tomorrow']},
        'wnba': {'id': 94682, 'date_ranges': ['today', 'tomorrow']},
        'nba': {'id': 42648, 'date_ranges': ['today', 'tomorrow']},
        'nhl': {'id': 42133, 'date_ranges': ['today', 'tomorrow']},
        'mls': {'id': 89345, 'date_ranges': ['today']},  # Soccer: today only
        'ufc': {'id': 9034, 'date_ranges': ['today', 'tomorrow']},
        'nfl': {'id': 88808, 'date_ranges': ['today', 'tomorrow']},
        'ncaaf': {'id': 87637, 'date_ranges': ['today', 'tomorrow']},
        'ncaa_basketball': {'id': 92483, 'date_ranges': ['today', 'tomorrow']},
        'ncaa_womens_basketball': {'id': 36647, 'date_ranges': ['today', 'tomorrow']},
        'ncaa_baseball': {'id': 41151, 'date_ranges': ['today', 'tomorrow']},
        'ncaa_ice_hockey': {'id': 84813, 'date_ranges': ['today', 'tomorrow']},
        'premier_league': {'id': 40253, 'date_ranges': ['today']},  # Soccer: today only
        'champions_league': {'id': 40685, 'date_ranges': ['today']},  # Soccer: today only
        'europa_league': {'id': 41410, 'date_ranges': ['today']},  # Soccer: today only
    }
   
    all_games_data = []
   
    # Skip the "all_sports" page - just get individual sports for cleaner data
    print("Scraping individual sports for today and tomorrow...")
   
    # Scrape each sport for both today and tomorrow
    for sport_name, config in sport_configs.items():
        if sport_name == 'all_sports':
            continue
           
        sport_id = config['id']
        date_ranges = config['date_ranges']
       
        print(f"Scraping {sport_name} (ID: {sport_id})...")
        sport_total_games = 0
       
        # Loop through each date range for this sport (today, tomorrow)
        for date_range in date_ranges:
            print(f"  Scraping {sport_name} for {date_range}...")
            page = 1
           
            while True:
                try:
                    if page == 1:
                        url = f"{base_url}?tb_eg={sport_id}&tb_edate={date_range}&tb_emt=0"
                    else:
                        url = f"{base_url}?tb_eg={sport_id}&tb_edate={date_range}&tb_page={page}"
                   
                    print(f"    Scraping {sport_name} page {page} ({date_range})...")
                    response = requests.get(url)
                    response.raise_for_status()
                    soup = BeautifulSoup(response.content, 'html.parser')
                   
                    games = soup.find_all('div', class_='tb-se')
                    print(f"      Found {len(games)} game divs on {sport_name} page {page}")
                   
                    if not games:
                        print(f"      No games found on {sport_name} page {page}, stopping")
                        break
                   
                    page_games = []
                    for game in games:
                        game_data = parse_game(game)
                        if game_data:
                            print(f"        Parsed game: {game_data['title']}")
                            # Add date range info to game data
                            game_data['scraped_date_range'] = date_range
                           
                            # Check if we already have this exact game (avoid duplicates)
                            duplicate = any(existing['title'] == game_data['title'] and
                                          existing['time'] == game_data['time'] and
                                          existing['scraped_date_range'] == game_data['scraped_date_range']
                                          for existing in all_games_data)
                            if not duplicate:
                                page_games.append(game_data)
                                all_games_data.append(game_data)
                            else:
                                print(f"        Skipping duplicate: {game_data['title']}")
                        else:
                            print(f"        Failed to parse a game on {sport_name} page {page}")
                   
                    if not page_games:
                        print(f"      No new games found on {sport_name} page {page}, stopping")
                        break
                   
                    sport_total_games += len(page_games)
                    print(f"      Found {len(page_games)} new games on {sport_name} page {page}")
                   
                    page += 1
                   
                    # Safety check to prevent infinite loops
                    if page > 20:
                        print(f"      Reached maximum page limit (20) for {sport_name}, stopping")
                        break
                       
                except Exception as e:
                    print(f"      Error scraping {sport_name} page {page}: {e}")
                    break
       
        print(f"  Total new games found for {sport_name}: {sport_total_games}")
        print()
   
    print(f"Total unique games scraped: {len(all_games_data)}")
    return all_games_data

def parse_game(game_soup):
    """Parse individual game data"""
    try:
        # Get game title and time
        title_elem = game_soup.find('div', class_='tb-se-title')
        if not title_elem:
            return None
           
        title = title_elem.find('h5').text.strip()
        time = title_elem.find('span').text.strip()
       
        # Extract teams from title - handle different formats
        if ' @ ' in title:
            # Format: "Team A @ Team B" (MLB, WNBA)
            teams = title.split(' @ ')
            if len(teams) == 2:
                away_team = teams[0].strip()
                home_team = teams[1].strip()
            else:
                print(f"    Cannot parse @ format: '{title}'")
                return None
        elif ' vs ' in title:
            # Format: "Team A vs Team B" (UFC, MLS)
            teams = title.split(' vs ')
            if len(teams) == 2:
                away_team = teams[0].strip()
                home_team = teams[1].strip()
            else:
                print(f"    Cannot parse vs format: '{title}'")
                return None
        else:
            print(f"    Cannot parse title format: '{title}'")
            return None
       
        # Find the main market wrapper
        market_wrapper = game_soup.find('div', class_='tb-market-wrap')
        if not market_wrapper:
            return None
           
        # Find all market sections - each has a header (tb-se-head) followed by data (tb-sm)
        market_containers = market_wrapper.find_all('div', recursive=False)
       
        game_data = {
            'title': title,
            'time': time,
            'away_team': away_team,
            'home_team': home_team,
            'markets': {}
        }
       
        for container in market_containers:
            market_data = parse_market(container)
            if market_data:
                game_data['markets'][market_data['type']] = market_data['bets']
       
        return game_data
   
    except Exception as e:
        print(f"Error parsing game: {e}")
        return None

def parse_market(market_soup):
    """Parse individual betting market (Moneyline, Spread, Total)"""
    try:
        # Get market type
        header = market_soup.find('div', class_='tb-se-head')
        if not header:
            return None
           
        market_type = header.find('div').text.strip()
       
        # Get all bets in this market
        bets = market_soup.find_all('div', class_='tb-sodd')
       
        market_bets = []
       
        for bet in bets:
            bet_data = parse_bet(bet)
            if bet_data:
                market_bets.append(bet_data)
       
        return {
            'type': market_type,
            'bets': market_bets
        }
   
    except Exception as e:
        print(f"Error parsing market: {e}")
        return None

def parse_bet(bet_soup):
    """Parse individual bet data"""
    try:
        # Get team/bet name
        team_elem = bet_soup.find('div', class_='tb-slipline')
        if not team_elem:
            return None
        team = team_elem.text.strip()
       
        # Get odds
        odds_elem = bet_soup.find('a', class_='tb-odd-s')
        if not odds_elem:
            return None
        odds = odds_elem.text.strip()
       
        # Get percentages - find all divs with % in text
        all_divs = bet_soup.find_all('div')
        percentages = []
       
        for div in all_divs:
            text = div.text.strip()
            if '%' in text and text.replace('%', '').replace(' ', '').isdigit():
                percentages.append(text)
       
        # Should have 2 percentages: handle % and bets %
        if len(percentages) >= 2:
            handle_pct = percentages[0]
            bets_pct = percentages[1]
        else:
            handle_pct = "0%"
            bets_pct = "0%"
       
        return {
            'team': team,
            'odds': odds,
            'handle_pct': handle_pct,
            'bets_pct': bets_pct
        }
   
    except Exception as e:
        print(f"Error parsing bet: {e}")
        return None

def extract_all_bets(games):
    """Extract all individual bets from all games for analysis"""
    all_bets = []
   
    for game in games:
        for market_type, bets in game['markets'].items():
            for bet in bets:
                # Add context to each bet
                bet_with_context = {
                    **bet,
                    'game_title': game['title'],
                    'game_time': game['time'],
                    'away_team': game['away_team'],
                    'home_team': game['home_team'],
                    'market_type': market_type
                }
                all_bets.append(bet_with_context)
   
    return all_bets

def parse_percentage(pct_str):
    """Convert percentage string to float"""
    try:
        return float(pct_str.replace('%', ''))
    except:
        return 0.0

def parse_odds(odds_str):
    """Convert odds string to numeric value for comparison"""
    try:
        # Remove unicode minus and convert to regular minus
        odds_str = odds_str.replace('−', '-')
        return int(odds_str)
    except:
        return 0

def big_bettor_alerts(games, limit=7):
    """Find picks with highest handle % of the day (exclude totals)"""
    all_bets = extract_all_bets(games)
   
    # Filter out totals (Over/Under bets)
    non_total_bets = [bet for bet in all_bets if bet['market_type'] != 'Total']
   
    # Sort by handle percentage (descending)
    sorted_bets = sorted(non_total_bets, key=lambda x: parse_percentage(x['handle_pct']), reverse=True)
   
    return sorted_bets[:limit]

def sharpest_longshot_bets(games, limit=7):
    """Find longshot bets (+200 or more) with at least 30% higher handle% than bet%"""
    all_bets = extract_all_bets(games)
   
    sharp_longshots = []
   
    for bet in all_bets:
        odds = parse_odds(bet['odds'])
        handle_pct = parse_percentage(bet['handle_pct'])
        bets_pct = parse_percentage(bet['bets_pct'])
       
        # Check if it's a longshot (+200 or more)
        if odds >= 200:
            # Check if handle% is at least 30% higher than bet%
            if handle_pct >= (bets_pct + 30):
                bet['handle_vs_bets_diff'] = handle_pct - bets_pct
                sharp_longshots.append(bet)
   
    # Sort by handle vs bets difference (descending)
    sorted_longshots = sorted(sharp_longshots, key=lambda x: x['handle_vs_bets_diff'], reverse=True)
   
    return sorted_longshots[:limit]

def get_rich_quick_scheme(games):
    """Find huge underdogs (+400 or more) getting at least 30% of the money"""
    all_bets = extract_all_bets(games)
   
    rich_quick_bets = []
   
    for bet in all_bets:
        odds = parse_odds(bet['odds'])
        handle_pct = parse_percentage(bet['handle_pct'])
       
        # Check if it's a huge underdog (+400 or more) with at least 30% handle
        if odds >= 400 and handle_pct >= 30:
            rich_quick_bets.append(bet)
   
    # Sort by handle percentage (descending)
    sorted_bets = sorted(rich_quick_bets, key=lambda x: parse_percentage(x['handle_pct']), reverse=True)
   
    return sorted_bets

def biggest_square_bets(games, limit=7):
    """Find picks with biggest discrepancy between bet% and handle% (high bet%, low handle%)"""
    all_bets = extract_all_bets(games)
   
    square_bets = []
   
    for bet in all_bets:
        handle_pct = parse_percentage(bet['handle_pct'])
        bets_pct = parse_percentage(bet['bets_pct'])
       
        # Calculate square score (bet% - handle%)
        square_score = bets_pct - handle_pct
       
        # Only include if bet% is significantly higher than handle%
        if square_score > 0:
            bet['square_score'] = square_score
            square_bets.append(bet)
   
    # Sort by square score (descending)
    sorted_square = sorted(square_bets, key=lambda x: x['square_score'], reverse=True)
   
    return sorted_square[:limit]

def filter_mlb_games(games):
    """Filter for MLB games only"""
    mlb_games = []
   
    # Common MLB team abbreviations and names
    mlb_teams = [
        'Angels', 'Astros', 'Athletics', 'Blue Jays', 'Braves', 'Brewers',
        'Cardinals', 'Cubs', 'Diamondbacks', 'Dodgers', 'Giants', 'Guardians',
        'Indians', 'Mariners', 'Marlins', 'Mets', 'Nationals', 'Orioles',
        'Padres', 'Phillies', 'Pirates', 'Rangers', 'Rays', 'Red Sox',
        'Reds', 'Rockies', 'Royals', 'Tigers', 'Twins', 'White Sox', 'Yankees',
        'LAA', 'HOU', 'OAK', 'TOR', 'ATL', 'MIL', 'STL', 'CHC', 'ARI', 'LAD',
        'SF', 'CLE', 'SEA', 'MIA', 'NYM', 'WSN', 'WAS', 'BAL', 'SD', 'PHI',
        'PIT', 'TEX', 'TB', 'BOS', 'CIN', 'COL', 'KC', 'DET', 'MIN', 'CWS',
        'CHW', 'NYY', 'NY'
    ]
   
    for game in games:
        # Check if any MLB team names appear in the game title
        title_upper = game['title'].upper()
        is_mlb = any(team.upper() in title_upper for team in mlb_teams)
       
        if is_mlb:
            mlb_games.append(game)
   
    return mlb_games

def filter_games_by_sport(games, sport):
    """Filter games by sport using team names"""
    
    # Team lists with ONLY team names and abbreviations (no city names)
    team_lists = {
        'mlb': [
            # Full team names
            'Angels', 'Astros', 'Athletics', 'Blue Jays', 'Braves', 'Brewers',
            'Cardinals', 'Cubs', 'Diamondbacks', 'Dodgers', 'Giants', 'Guardians',
            'Mariners', 'Marlins', 'Mets', 'Nationals', 'Orioles', 'Padres', 
            'Phillies', 'Pirates', 'Rangers', 'Rays', 'Red Sox', 'Reds', 'Rockies', 
            'Royals', 'Tigers', 'Twins', 'White Sox', 'Yankees',
            # Abbreviations
            'LAA', 'HOU', 'OAK', 'TOR', 'ATL', 'MIL', 'STL', 'CHC', 'ARI', 'LAD',
            'SF', 'CLE', 'MIA', 'NYM', 'WSN', 'WAS', 'BAL', 'SD', 'PHI',
            'PIT', 'TEX', 'TB', 'BOS', 'CIN', 'COL', 'KC', 'DET', 'MIN', 'CWS',
            'CHW', 'NYY'
        ],
        'nba': [
            # Full team names
            'Hawks', 'Celtics', 'Nets', 'Hornets', 'Bulls', 'Cavaliers', 'Mavericks',
            'Nuggets', 'Pistons', 'Warriors', 'Rockets', 'Pacers', 'Clippers', 'Lakers',
            'Grizzlies', 'Heat', 'Bucks', 'Timberwolves', 'Pelicans', 'Knicks',
            'Thunder', 'Magic', '76ers', 'Suns', 'Trail Blazers', 'Kings', 'Spurs',
            'Raptors', 'Jazz', 'Wizards',
            # Abbreviations
            'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
            'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
            'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'
        ],
        'nfl': [
            # Full team names
            'Cardinals', 'Falcons', 'Ravens', 'Bills', 'Panthers', 'Bears', 'Bengals',
            'Browns', 'Cowboys', 'Broncos', 'Lions', 'Packers', 'Texans', 'Colts',
            'Jaguars', 'Chiefs', 'Raiders', 'Chargers', 'Rams', 'Dolphins', 'Vikings',
            'Patriots', 'Saints', 'Giants', 'Jets', 'Eagles', 'Steelers', '49ers',
            'Seahawks', 'Buccaneers', 'Titans', 'Commanders',
            # Abbreviations
            'ARI', 'ATL', 'BAL', 'BUF', 'CAR', 'CHI', 'CIN', 'CLE', 'DAL', 'DEN',
            'DET', 'GB', 'HOU', 'IND', 'JAX', 'KC', 'LV', 'LAC', 'LAR', 'MIA',
            'MIN', 'NE', 'NO', 'NYG', 'NYJ', 'PHI', 'PIT', 'SF', 'TEN', 'WAS'
        ],
        'nhl': [
            # Full team names
            'Ducks', 'Coyotes', 'Bruins', 'Sabres', 'Flames', 'Hurricanes',
            'Blackhawks', 'Avalanche', 'Blue Jackets', 'Stars', 'Red Wings',
            'Oilers', 'Panthers', 'Kings', 'Wild', 'Canadiens', 'Predators',
            'Devils', 'Islanders', 'Rangers', 'Senators', 'Flyers', 'Penguins',
            'Sharks', 'Kraken', 'Blues', 'Lightning', 'Maple Leafs', 'Canucks',
            'Golden Knights', 'Capitals', 'Jets',
            # Abbreviations
            'ANA', 'ARI', 'BOS', 'BUF', 'CGY', 'CAR', 'CHI', 'COL', 'CBJ', 'DAL',
            'DET', 'EDM', 'FLA', 'LAK', 'MIN', 'MTL', 'NSH', 'NJD', 'NYI', 'NYR',
            'OTT', 'PHI', 'PIT', 'SJS', 'STL', 'TBL', 'TOR', 'VAN', 'VGK',
            'WSH', 'WPG'
        ]
    }
    
    if sport not in team_lists:
        return []
    
    sport_games = []
    sport_teams = team_lists[sport]
    
    for game in games:
        # Check if any team names from this sport appear in the game title
        title_upper = game['title'].upper()
        is_sport_game = any(team.upper() in title_upper for team in sport_teams)
        
        if is_sport_game:
            sport_games.append(game)
    
    return sport_games

def big_bettor_alerts_by_sport(games, sport, limit=7):
    """Find picks with biggest difference between handle % and bets % for specific sport"""
    # Filter games by sport
    sport_games = filter_games_by_sport(games, sport)
    
    if not sport_games:
        return []
    
    # Extract all bets from sport games
    all_bets = extract_all_bets(sport_games)
    
    # Filter out totals (Over/Under bets)
    non_total_bets = [bet for bet in all_bets if bet['market_type'] != 'Total']
    
    # Calculate handle% - bets% difference for each bet
    for bet in non_total_bets:
        handle_pct = parse_percentage(bet['handle_pct'])
        bets_pct = parse_percentage(bet['bets_pct'])
        bet['handle_vs_bets_diff'] = handle_pct - bets_pct
    
    # Sort by handle vs bets difference (descending)
    sorted_bets = sorted(non_total_bets, key=lambda x: x['handle_vs_bets_diff'], reverse=True)
    
    return sorted_bets[:limit]

def biggest_square_bets_by_sport(games, sport, limit=7):
    """Find picks with biggest discrepancy between bet% and handle% for specific sport"""
    # Filter games by sport
    sport_games = filter_games_by_sport(games, sport)
    
    if not sport_games:
        return []
    
    # Extract all bets from sport games
    all_bets = extract_all_bets(sport_games)
    
    square_bets = []
    
    for bet in all_bets:
        handle_pct = parse_percentage(bet['handle_pct'])
        bets_pct = parse_percentage(bet['bets_pct'])
        
        # Calculate square score (bet% - handle%)
        square_score = bets_pct - handle_pct
        
        # Only include if bet% is significantly higher than handle%
        if square_score > 0:
            bet['square_score'] = square_score
            square_bets.append(bet)
    
    # Sort by square score (descending)
    sorted_square = sorted(square_bets, key=lambda x: x['square_score'], reverse=True)
    
    return sorted_square[:limit]

# Flask routes
@app.route('/')
def home():
    cache_status = f"Cache: {'Active' if cached_games_data else 'Empty'}"
    if cache_timestamp:
        cache_age = datetime.now() - cache_timestamp
        cache_status += f" (Age: {cache_age})"
    
    return f"""
    <h1>DraftKings Betting Splits Scraper</h1>
    <p><strong>{cache_status}</strong></p>
    <p>Cache Duration: {CACHE_DURATION_MINUTES} minutes</p>
    <h2>Data Endpoints:</h2>
    <ul>
        <li><a href="/all">/all</a> - All sports betting splits</li>
        <li><a href="/mlb">/mlb</a> - MLB betting splits only</li>
        <li><a href="/test">/test</a> - Test endpoint (first game)</li>
    </ul>
    <h2>Analytics Endpoints:</h2>
    <ul>
        <li><a href="/big-bettor-alerts">/big-bettor-alerts</a> - 7 picks with highest handle % of the day</li>
        <li><a href="/sharpest-longshots">/sharpest-longshots</a> - Longshot bets (+200+) with 30%+ higher handle than bets</li>
        <li><a href="/get-rich-quick">/get-rich-quick</a> - Huge underdogs (+400+) getting 30%+ of money</li>
        <li><a href="/biggest-square-bets">/biggest-square-bets</a> - Biggest discrepancy between bet% and handle%</li>
        <li><a href="/analytics-summary">/analytics-summary</a> - Summary of all analytics</li>
    </ul>
    <h2>Sports-Specific Big Bettor Alerts:</h2>
    <ul>
        <li><a href="/big-bettor-alerts-mlb">/big-bettor-alerts-mlb</a> - MLB biggest handle% vs bets% difference</li>
        <li><a href="/big-bettor-alerts-nba">/big-bettor-alerts-nba</a> - NBA biggest handle% vs bets% difference</li>
        <li><a href="/big-bettor-alerts-nfl">/big-bettor-alerts-nfl</a> - NFL biggest handle% vs bets% difference</li>
        <li><a href="/big-bettor-alerts-nhl">/big-bettor-alerts-nhl</a> - NHL biggest handle% vs bets% difference</li>
    </ul>
    <h2>Sports-Specific Square Bets:</h2>
    <ul>
        <li><a href="/biggest-square-bets-mlb">/biggest-square-bets-mlb</a> - MLB biggest square bets</li>
        <li><a href="/biggest-square-bets-nba">/biggest-square-bets-nba</a> - NBA biggest square bets</li>
        <li><a href="/biggest-square-bets-nfl">/biggest-square-bets-nfl</a> - NFL biggest square bets</li>
        <li><a href="/biggest-square-bets-nhl">/biggest-square-bets-nhl</a> - NHL biggest square bets</li>
    </ul>
    <h2>Cache Management:</h2>
    <ul>
        <li><a href="/refresh-cache">/refresh-cache</a> - Force refresh the data cache</li>
    </ul>
    """

@app.route('/all')
def get_all_games():
    """Get all sports betting splits"""
    games = get_cached_or_fresh_data()
    return jsonify({
        'games': games,
        'count': len(games),
        'cached': bool(cached_games_data),
        'cache_age_minutes': (datetime.now() - cache_timestamp).total_seconds() / 60 if cache_timestamp else 0
    })

@app.route('/mlb')
def get_mlb_games():
    """Get MLB betting splits only"""
    all_games = get_cached_or_fresh_data()
    mlb_games = filter_mlb_games(all_games)
    return jsonify({
        'games': mlb_games,
        'count': len(mlb_games),
        'cached': bool(cached_games_data),
        'cache_age_minutes': (datetime.now() - cache_timestamp).total_seconds() / 60 if cache_timestamp else 0
    })

@app.route('/test')
def test_scraper():
    """Test the scraper with first few games"""
    games = get_cached_or_fresh_data()
    return jsonify({
        'first_game': games[0] if games else None,
        'total_games': len(games),
        'cached': bool(cached_games_data),
        'cache_age_minutes': (datetime.now() - cache_timestamp).total_seconds() / 60 if cache_timestamp else 0
    })

@app.route('/refresh-cache')
def refresh_cache():
    """Force refresh the data cache"""
    global cached_games_data, cache_timestamp
    print("Forcing cache refresh...")
    cached_games_data = []
    cache_timestamp = None
    games = get_cached_or_fresh_data()
    return jsonify({
        'message': 'Cache refreshed successfully',
        'total_games': len(games),
        'cache_timestamp': cache_timestamp.isoformat() if cache_timestamp else None
    })

# Analytics endpoints
@app.route('/big-bettor-alerts')
def get_big_bettor_alerts():
    """Get 7 picks with highest handle % of the day"""
    all_games = get_cached_or_fresh_data()
    alerts = big_bettor_alerts(all_games)
    return jsonify({
        'big_bettor_alerts': alerts,
        'count': len(alerts),
        'description': 'Picks with the highest handle % of the day (no totals)',
        'cached': bool(cached_games_data)
    })

@app.route('/sharpest-longshots')
def get_sharpest_longshots():
    """Get longshot bets (+200 or more) with at least 30% higher handle% than bet%"""
    all_games = get_cached_or_fresh_data()
    longshots = sharpest_longshot_bets(all_games)
    return jsonify({
        'sharpest_longshots': longshots,
        'count': len(longshots),
        'description': 'Longshot bets (+200 or more) with at least 30% higher handle% than bet%',
        'cached': bool(cached_games_data)
    })

@app.route('/get-rich-quick')
def get_rich_quick():
    """Get huge underdogs (+400 or more) getting at least 30% of the money"""
    all_games = get_cached_or_fresh_data()
    rich_quick = get_rich_quick_scheme(all_games)
    return jsonify({
        'get_rich_quick': rich_quick,
        'count': len(rich_quick),
        'description': 'Huge underdogs (+400 or more) getting at least 30% of the money',
        'cached': bool(cached_games_data)
    })

@app.route('/biggest-square-bets')
def get_biggest_square_bets():
    """Get picks with biggest discrepancy between bet% and handle% (high bet%, low handle%)"""
    all_games = get_cached_or_fresh_data()
    square_bets = biggest_square_bets(all_games)
    return jsonify({
        'biggest_square_bets': square_bets,
        'count': len(square_bets),
        'description': 'Picks with biggest discrepancy between bet% and handle% (high bet%, low handle%)',
        'cached': bool(cached_games_data)
    })

@app.route('/analytics-summary')
def get_analytics_summary():
    """Get a summary of all analytics"""
    all_games = get_cached_or_fresh_data()
    mlb_games = filter_mlb_games(all_games)
   
    return jsonify({
        'summary': {
            'total_games': len(all_games),
            'mlb_games': len(mlb_games),
            'big_bettor_alerts': len(big_bettor_alerts(all_games)),
            'sharpest_longshots': len(sharpest_longshot_bets(all_games)),
            'get_rich_quick': len(get_rich_quick_scheme(all_games)),
            'biggest_square_bets': len(biggest_square_bets(all_games)),
            'cached': bool(cached_games_data)
        }
    })

# NEW SPORTS-SPECIFIC ENDPOINTS

@app.route('/big-bettor-alerts-mlb')
def get_big_bettor_alerts_mlb():
    """Get MLB big bettor alerts (biggest handle% vs bets% difference)"""
    all_games = get_cached_or_fresh_data()
    alerts = big_bettor_alerts_by_sport(all_games, 'mlb')
    return jsonify({
        'big_bettor_alerts_mlb': alerts,
        'count': len(alerts),
        'description': 'MLB picks with the biggest difference between handle % and bets %',
        'cached': bool(cached_games_data)
    })

@app.route('/big-bettor-alerts-nba')
def get_big_bettor_alerts_nba():
    """Get NBA big bettor alerts (biggest handle% vs bets% difference)"""
    all_games = get_cached_or_fresh_data()
    alerts = big_bettor_alerts_by_sport(all_games, 'nba')
    return jsonify({
        'big_bettor_alerts_nba': alerts,
        'count': len(alerts),
        'description': 'NBA picks with the biggest difference between handle % and bets %',
        'cached': bool(cached_games_data)
    })

@app.route('/big-bettor-alerts-nfl')
def get_big_bettor_alerts_nfl():
    """Get NFL big bettor alerts (biggest handle% vs bets% difference)"""
    all_games = get_cached_or_fresh_data()
    alerts = big_bettor_alerts_by_sport(all_games, 'nfl')
    return jsonify({
        'big_bettor_alerts_nfl': alerts,
        'count': len(alerts),
        'description': 'NFL picks with the biggest difference between handle % and bets %',
        'cached': bool(cached_games_data)
    })

@app.route('/big-bettor-alerts-nhl')
def get_big_bettor_alerts_nhl():
    """Get NHL big bettor alerts (biggest handle% vs bets% difference)"""
    all_games = get_cached_or_fresh_data()
    alerts = big_bettor_alerts_by_sport(all_games, 'nhl')
    return jsonify({
        'big_bettor_alerts_nhl': alerts,
        'count': len(alerts),
        'description': 'NHL picks with the biggest difference between handle % and bets %',
        'cached': bool(cached_games_data)
    })

@app.route('/biggest-square-bets-mlb')
def get_biggest_square_bets_mlb():
    """Get MLB biggest square bets"""
    all_games = get_cached_or_fresh_data()
    square_bets = biggest_square_bets_by_sport(all_games, 'mlb')
    return jsonify({
        'biggest_square_bets_mlb': square_bets,
        'count': len(square_bets),
        'description': 'MLB picks with biggest discrepancy between bet% and handle% (high bet%, low handle%)',
        'cached': bool(cached_games_data)
    })

@app.route('/biggest-square-bets-nba')
def get_biggest_square_bets_nba():
    """Get NBA biggest square bets"""
    all_games = get_cached_or_fresh_data()
    square_bets = biggest_square_bets_by_sport(all_games, 'nba')
    return jsonify({
        'biggest_square_bets_nba': square_bets,
        'count': len(square_bets),
        'description': 'NBA picks with biggest discrepancy between bet% and handle% (high bet%, low handle%)',
        'cached': bool(cached_games_data)
    })

@app.route('/biggest-square-bets-nfl')
def get_biggest_square_bets_nfl():
    """Get NFL biggest square bets"""
    all_games = get_cached_or_fresh_data()
    square_bets = biggest_square_bets_by_sport(all_games, 'nfl')
    return jsonify({
        'biggest_square_bets_nfl': square_bets,
        'count': len(square_bets),
        'description': 'NFL picks with biggest discrepancy between bet% and handle% (high bet%, low handle%)',
        'cached': bool(cached_games_data)
    })

@app.route('/biggest-square-bets-nhl')
def get_biggest_square_bets_nhl():
    """Get NHL biggest square bets"""
    all_games = get_cached_or_fresh_data()
    square_bets = biggest_square_bets_by_sport(all_games, 'nhl')
    return jsonify({
        'biggest_square_bets_nhl': square_bets,
        'count': len(square_bets),
        'description': 'NHL picks with biggest discrepancy between bet% and handle% (high bet%, low handle%)',
        'cached': bool(cached_games_data)
    })

if __name__ == '__main__':
    # Test the scraper and compute all analytics
    print("Testing scraper...")
    games = scrape_betting_splits()
   
    # Cache the data globally
    cached_games_data = games
    cache_timestamp = datetime.now()
   
    print(f"Found {len(games)} games")
   
    if games:
        print("\nFirst game:")
        print(f"Title: {games[0]['title']}")
        print(f"Time: {games[0]['time']}")
        print(f"Markets: {list(games[0]['markets'].keys())}")
        print(f"Date Range: {games[0]['scraped_date_range']}")
   
    # Compute all analytics on startup
    print("\n" + "="*50)
    print("COMPUTING ALL ANALYTICS")
    print("="*50)
   
    # Big Bettor Alerts
    print("\n🔥 BIG BETTOR ALERTS (Top 7 - No Totals)")
    big_bettors = big_bettor_alerts(games)
    for i, bet in enumerate(big_bettors, 1):
        print(f"{i}. {bet['team']} ({bet['odds']}) - {bet['handle_pct']} handle | {bet['game_title']} | {bet['market_type']}")
   
    # Sharpest Longshots
    print("\n🎯 SHARPEST LONGSHOTS (+200 odds, 30%+ handle advantage)")
    longshots = sharpest_longshot_bets(games)
    for i, bet in enumerate(longshots, 1):
        diff = bet['handle_vs_bets_diff']
        print(f"{i}. {bet['team']} ({bet['odds']}) - {bet['handle_pct']} handle vs {bet['bets_pct']} bets (+{diff:.1f}%) | {bet['game_title']}")
   
    # Get Rich Quick
    print("\n💰 GET RICH QUICK SCHEME (+400 odds, 30%+ money)")
    rich_quick = get_rich_quick_scheme(games)
    for i, bet in enumerate(rich_quick, 1):
        print(f"{i}. {bet['team']} ({bet['odds']}) - {bet['handle_pct']} handle | {bet['game_title']}")
   
    # Biggest Square Bets
    print("\n🤡 BIGGEST SQUARE BETS (High bets%, low handle%)")
    squares = biggest_square_bets(games)
    for i, bet in enumerate(squares, 1):
        score = bet['square_score']
        print(f"{i}. {bet['team']} ({bet['odds']}) - {bet['bets_pct']} bets vs {bet['handle_pct']} handle (+{score:.1f}% square) | {bet['game_title']}")
   
    # NEW: Sports-specific analytics preview
    print("\n📊 SPORTS-SPECIFIC BIG BETTOR ALERTS PREVIEW")
    for sport in ['mlb', 'nba', 'nfl', 'nhl']:
        sport_alerts = big_bettor_alerts_by_sport(games, sport, limit=3)
        print(f"\n{sport.upper()} Top 3:")
        for i, bet in enumerate(sport_alerts, 1):
            diff = bet['handle_vs_bets_diff']
            print(f"  {i}. {bet['team']} ({bet['odds']}) - {bet['handle_pct']} handle vs {bet['bets_pct']} bets (+{diff:.1f}%) | {bet['game_title']}")
   
    # Analytics Summary
    print("\n📊 ANALYTICS SUMMARY")
    mlb_games = filter_mlb_games(games)
    nba_games = filter_games_by_sport(games, 'nba')
    nfl_games = filter_games_by_sport(games, 'nfl')
    nhl_games = filter_games_by_sport(games, 'nhl')
    print(f"Total games: {len(games)}")
    print(f"MLB games: {len(mlb_games)}")
    print(f"NBA games: {len(nba_games)}")
    print(f"NFL games: {len(nfl_games)}")
    print(f"NHL games: {len(nhl_games)}")
    print(f"Big bettor alerts: {len(big_bettors)}")
    print(f"Sharpest longshots: {len(longshots)}")
    print(f"Get rich quick bets: {len(rich_quick)}")
    print(f"Biggest square bets: {len(squares)}")
   
    print("\n" + "="*50)
    print("Starting Flask server...")
    print(f"Data is cached for {CACHE_DURATION_MINUTES} minutes")
    print("Visit /refresh-cache to force new scraping")
    print("="*50)
   
    # Start Flask app
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
