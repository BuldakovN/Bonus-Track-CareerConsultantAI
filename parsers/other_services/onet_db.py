import pandas as pd
import json
from pathlib import Path

# Папка с файлами
data_dir = Path("data/db_onet")

# Загрузка Excel
abilities_df = pd.read_excel(data_dir / "Abilities.xlsx")
skills_df = pd.read_excel(data_dir / "Skills.xlsx")
knowledge_df = pd.read_excel(data_dir / "Knowledge.xlsx")
tasks_df = pd.read_excel(data_dir / "Task Statements.xlsx")
occupation_df = pd.read_excel(data_dir / "Occupation Data.xlsx")

# Функция для выбора топ-N по Importance (IM)
def top_n_importance(df, n=6):
    df_im = df[df['Scale ID'] == 'IM']
    top_df = df_im.groupby('O*NET-SOC Code').apply(lambda x: x.nlargest(n, 'Data Value')).reset_index(drop=True)
    result = {}
    for code, group in top_df.groupby('O*NET-SOC Code'):
        result[code] = [{'name': row['Element Name'], 'value': row['Data Value']} for idx, row in group.iterrows()]
    return result

# Получаем топ-6 для навыков, умений, знаний
top_skills = top_n_importance(skills_df)
top_abilities = top_n_importance(abilities_df)
top_knowledge = top_n_importance(knowledge_df)

# Формируем JSON
output_path = Path('data/onet_data.json')
output_path.parent.mkdir(parents=True, exist_ok=True)
num_occupations = occupation_df.shape[0]
with open(output_path, 'w', encoding='utf-8') as f:
    f.write('{\n')
    for i, (_, row) in enumerate(occupation_df.iterrows()):
        code = row['O*NET-SOC Code']
        entry = {
            'title': row['Title'],
            'description': row['Description'],
            'skills': top_skills.get(code, []),
            'abilities': top_abilities.get(code, []),
            'knowledge': top_knowledge.get(code, []),
            'tasks': tasks_df[tasks_df['O*NET-SOC Code'] == code]['Task'].tolist()
        }
        json_str = json.dumps({code: entry}, ensure_ascii=False, indent=4)[1:-1]  # remove { and }
        if i > 0:
            f.write(',\n')
        f.write(json_str)
        print(f'Обработано профессий: {i+1}/{num_occupations}')
    f.write('\n}\n')
print("JSON файл onet_data.json успешно сформирован!")