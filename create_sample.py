import pandas as pd

def create_sample_excel():
    data = {
        "id": [1, 2, 3],
        "category": ["Pricing", "Location", "Hours"],
        "keywords": ["price, cost, fee, money", "where, address, location", "time, open, close, hours"],
        "question": ["How much does it cost?", "Where are you located?", "What are your business hours?"],
        "answer": ["Our basic plan starts at $10/month.", "We are located at 123 Main St.", "We are open 9 AM to 5 PM, Mon-Fri."]
    }
    df = pd.DataFrame(data)
    df.to_excel("faq.xlsx", index=False)
    print("Successfully created faq.xlsx")

if __name__ == "__main__":
    create_sample_excel()
