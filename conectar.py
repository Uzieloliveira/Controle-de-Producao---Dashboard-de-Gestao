import os
import firebase_admin
from firebase_admin import credentials, firestore

# Carrega a chave de autenticação do seu projeto existente
cred_path = os.path.join(os.path.dirname(__file__), "serviceAccountKey.json")
cred = credentials.Certificate(cred_path)

# Inicializa o Firebase
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

# Conecta ao Firestore mantendo acesso aos seus dados atuais
db = firestore.client()

print("Conectado ao Firestore com sucesso!")

# Exemplo rápido para listar documentos de uma coleção existente (substitua 'sua_colecao' pelo nome real)
# colecao_ref = db.collection('sua_colecao')
# for doc in colecao_ref.stream():
#     print(f'{doc.id} => {doc.to_dict()}')