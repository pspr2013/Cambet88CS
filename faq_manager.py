import pandas as pd
from rapidfuzz import fuzz
import os
import asyncio
import logging

logger = logging.getLogger(__name__)

class FAQManager:
    def __init__(self, file_path):
        self.file_path = file_path
        self.df = None
        self.last_modified = 0
        self.categories = []
        self.load_data()

    def load_data(self):
        try:
            if not os.path.exists(self.file_path):
                logger.warning(f"FAQ file {self.file_path} not found.")
                self.df = pd.DataFrame(columns=["id", "category", "keywords", "question", "answer"])
                return False

            self.df = pd.read_excel(self.file_path)
            self.df = self.df.fillna("")
            self.last_modified = os.path.getmtime(self.file_path)
            self.categories = [c for c in self.df['category'].unique() if str(c).strip()]
            logger.info("FAQ data loaded successfully.")
            return True
        except Exception as e:
            logger.error(f"Error loading FAQ data: {e}")
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
                return row['answer']
            if user_text_lower in str(row['question']).lower():
                return row['answer']

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
                best_match = row['answer']

        if best_score >= 70:
            return best_match

        return None
        
    async def auto_reload_task(self):
        while True:
            await asyncio.sleep(60)
            try:
                if os.path.exists(self.file_path):
                    current_modified = os.path.getmtime(self.file_path)
                    if current_modified > self.last_modified:
                        logger.info("File modification detected. Reloading...")
                        self.load_data()
            except Exception as e:
                logger.error(f"Error in auto_reload_task: {e}")
