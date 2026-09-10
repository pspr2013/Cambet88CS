import pandas as pd
import asyncio
import logging
from fuzzywuzzy import process, fuzz

logger = logging.getLogger(__name__)

class FAQManager:
    def __init__(self, csv_url):
        self.csv_url = csv_url
        self.df = None
        self.load_data()

    def load_data(self):
        try:
            # We add dtype=str to ensure pandas doesn't convert numbers
            df = pd.read_csv(self.csv_url, dtype=str)
            df.fillna("", inplace=True)
            self.df = df
            logger.info("FAQ data loaded successfully from Google Sheets.")
            return True
        except Exception as e:
            logger.error(f"Failed to load FAQ data: {e}")
            return False

    async def auto_reload_task(self):
        while True:
            await asyncio.sleep(300)  # Reload every 5 minutes
            logger.info("Auto reloading data from Google Sheets in the background...")
            self.load_data()

    def get_categories(self):
        if self.df is None or self.df.empty:
            return []
        if 'category' not in self.df.columns:
            return []
        cats = self.df['category'].unique()
        return [c for c in cats if str(c).strip()]

    def find_answer(self, user_text):
        if self.df is None or self.df.empty:
            return None
            
        user_text_clean = str(user_text).strip().lower()
        if not user_text_clean:
            return None

        # --- FIX: EXACT MATCH CHECK ---
        # The bot will now check if the user typed EXACTLY what is in the Excel sheet
        # before it uses the fuzzy AI. This perfectly fixes the "?" issue!
        for index, row in self.df.iterrows():
            # Check keywords
            if 'keywords' in row and str(row['keywords']).strip():
                kws = [k.strip().lower() for k in str(row['keywords']).split(',')]
                if user_text_clean in kws:
                    return {"answer": str(row['answer']), "image_url": str(row.get('image_url', ''))}
                    
            # Check question
            if 'question' in row and str(row['question']).strip().lower() == user_text_clean:
                return {"answer": str(row['answer']), "image_url": str(row.get('image_url', ''))}
                
            # Check category
            if 'category' in row and str(row['category']).strip().lower() == user_text_clean:
                return {"answer": str(row['answer']), "image_url": str(row.get('image_url', ''))}

        # --- FUZZY MATCHING (Typo AI) ---
        best_match = None
        best_score = 0
        best_row = None

        for index, row in self.df.iterrows():
            choices = []
            if 'keywords' in row and str(row['keywords']).strip():
                choices.extend([k.strip() for k in str(row['keywords']).split(',')])
            if 'question' in row and str(row['question']).strip():
                choices.append(str(row['question']))

            if not choices:
                continue

            match = process.extractOne(user_text_clean, choices, scorer=fuzz.token_set_ratio)
            if match:
                score = match[1]
                if score > best_score:
                    best_score = score
                    best_row = row

        # If the fuzzy score is higher than 70%, we accept it
        if best_score > 70 and best_row is not None:
            return {
                "answer": str(best_row['answer']),
                "image_url": str(best_row.get('image_url', ''))
            }

        return None