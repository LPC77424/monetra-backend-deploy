from database import Base
from database import engine
import models  # importiere deine Models, z. B. Transaktion

print("📦 Starte Tabellen-Erstellung...")
Base.metadata.create_all(bind=engine)
print("✅ Tabellen wurden erfolgreich erstellt.")