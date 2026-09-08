import pandas as pd
from rapidfuzz import fuzz
import asyncio
import logging
import os

logger = logging.getLogger(__name__)

class FAQManager:
    def __init__(self, sheet_url):
        self.sheet_url = sheet_url
        self.df = None
        self.categories = []
        self.load_data()

    def load_data(self):
        try:
            if not self.sheet_url:
                logger.warning("GOOGLE_SHEET_URL is not set!")
                return False

            # Pandas can automatically download and read a CSV from a web link!
            self.df = pd.read_csv(self.sheet_url)
            
            if 'image_url' not in self.df.columns:
                self.df['image_url'] = ""
                
            self.df = self.df.fillna("")
            self.categories = [c for c in self.df['category'].unique() if str(c).strip()]
            logger.info("FAQ data loaded successfully from Google Sheets.")
            return True
        except Exception as e:
            logger.error(f"Error loading FAQ data from Google Sheets: {e}")
            return False

    def get_categories(self):
        return self.categories
        
    def get_questions_by_category(self, category):
        if self.df is None or self.df.empty:
            return []
        category_df = self.df[self.df['category'].str.lower() == category.lower()]
        return category_df['question'].tolist()

    def find_answer(self, user_text):
        if self.df is None or self.df.empty:
            return None

        user_text_lower = user_text.lower()

        # Step 1: Check for exact/partial keyword matches
        for index, row in self.df.iterrows():
            keywords = [k.strip().lower() for k in str(row['keywords']).split(',') if k.strip()]
            if any(k in user_text_lower for k in keywords):
                return {"answer": str(row['answer']), "image_url": str(row['image_url']).strip()}
            if user_text_lower in str(row['question']).lower():
                return {"answer": str(row['answer']), "image_url": str(row['image_url']).strip()}

        # Step 2: Fuzzy matching against questions and keywords
        best_match = None
        best_score = 0
        
        for index, row in self.df.iterrows():
            question = str(row['question'])
            keywords_str = str(row['keywords'])
            
            q_score = fuzz.partial_ratio(user_text_lower, question.lower())
            k_score = fuzz.partial_ratio(user_text_lower, keywords_str.lower())
            
            score = max(q_score, k_score)
            if score > best_score:
                best_score = score
                best_match = {"answer": str(row['answer']), "image_url": str(row['image_url']).strip()}

        if best_score >= 70:
            return best_match

        return None
        
    async def auto_reload_task(self):
        while True:
            # Check the Google Sheet every 5 minutes
            await asyncio.sleep(60 * 5)
            try:
                logger.info("Auto-reloading data from Google Sheets in the background...")
                # This forces the Google download to happen in a separate background thread, 
                # so your Telegram bot NEVER freezes or delays while waiting for Google!
                await asyncio.to_thread(self.load_data)
            except Exception as e:
                logger.error(f"Error in auto_reload_task: {e}")