# Generated by Django 3.2.5 on 2021-07-08 04:31

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='is_in_stock',
            field=models.BooleanField(default=True),
        ),
    ]