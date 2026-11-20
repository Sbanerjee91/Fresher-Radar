from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("jobs", "0003_tagging_and_dedupe")]

    operations = [migrations.AddField("synclog", "llm_cost_usd", models.FloatField(default=0))]
