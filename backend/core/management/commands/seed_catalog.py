from django.core.management.base import BaseCommand
from core.models import Product, Variant


class Command(BaseCommand):
    help = "Create an editable starter POPME catalog. Existing records are never overwritten."

    def handle(self, **options):
        flavors = [
            ("KAR", "Słony karmel", "#ce954b"),
            ("CZEK", "Czekolada", "#947061"),
            ("BIAL", "Palona biała czekolada", "#c9af7c"),
            ("ORZ", "Masło orzechowe", "#af8252"),
        ]
        for code, name, color in flavors:
            product, _ = Product.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "color": color,
                    "instruction": "Przygotuj popcorn zgodnie z aktualną instrukcją zakładową. Zgłoś dopiero produkt gotowy do pakowania.",
                },
            )
            for grams in [30, 100, 400]:
                for custom in [False, True]:
                    Variant.objects.get_or_create(
                        sku=f"{code}-{grams}" + ("-LOGO" if custom else ""),
                        defaults={
                            "product": product,
                            "name": name + (" z logo" if custom else ""),
                            "weight_g": grams,
                            "custom_label": custom,
                            "packaging": "Doypack kraft",
                            "instruction": "Sprawdź smak, gramaturę i etykietę. Zgrzej opakowanie.",
                        },
                    )
        self.stdout.write(
            "Starter catalog ready (editable; packaging and formats require your review)."
        )
