from __future__ import annotations

from urllib.parse import urlencode


def nutrition_tips_for_track(track_id: str, variant: int = 0) -> list[tuple[str, str, str]]:
    recipe_sets = {
        "atlet": [
            [
                ("Chicken with rice or quinoa", "Protein and carbohydrates for muscle growth, hard sessions, and recovery.", "https://www.ica.se/recept/?q=chicken%20quinoa"),
                ("Salmon with potatoes and vegetables", "Healthy fats, protein, and energy for performance-focused training.", "https://www.ica.se/recept/?q=salmon%20potatoes%20vegetables"),
                ("Greek yogurt or overnight oats with berries", "Convenient breakfast or evening meal with protein and slow carbohydrates.", "https://www.ica.se/recept/?q=overnight%20oats%20berries"),
                ("Turkey pasta with spinach", "A high-energy meal that supports heavy strength blocks and recovery.", "https://www.ica.se/recept/?q=turkey%20pasta%20spinach"),
                ("Tuna rice bowl with avocado", "Fast protein, carbohydrates, and fats for users training often.", "https://www.ica.se/recept/?q=tuna%20rice%20bowl"),
            ],
            [
                ("Beef stir-fry with noodles", "Iron, protein, and carbohydrates for performance and adaptation.", "https://www.ica.se/recept/?q=beef%20stir%20fry%20noodles"),
                ("Protein pancakes with cottage cheese", "Easy extra calories and protein when the goal is to build more.", "https://www.ica.se/recept/?q=protein%20pancakes%20cottage%20cheese"),
                ("Chicken burrito bowl", "A simple way to combine protein, rice, beans, and vegetables.", "https://www.ica.se/recept/?q=chicken%20burrito%20bowl"),
                ("Prawn omelet with sourdough toast", "Protein-rich meal with enough energy for a demanding week.", "https://www.ica.se/recept/?q=prawn%20omelet"),
                ("Cottage cheese smoothie bowl", "Useful snack after training when appetite is low.", "https://www.ica.se/recept/?q=cottage%20cheese%20smoothie%20bowl"),
            ],
        ],
        "komma-igang": [
            [
                ("Lentil soup with vegetables", "A filling meal with fiber and low energy density.", "https://www.ica.se/recept/?q=lentil%20soup%20vegetables"),
                ("Chicken salad with hearty vegetables", "Easy to portion and good for users who want to lose weight.", "https://www.ica.se/recept/?q=chicken%20salad"),
                ("Cod with vegetables and potatoes", "Lean protein with a simple everyday base.", "https://www.ica.se/recept/?q=cod%20vegetables%20potatoes"),
                ("Vegetable omelet with cottage cheese", "Quick, filling, and protein-rich without being complicated.", "https://www.ica.se/recept/?q=vegetable%20omelet%20cottage%20cheese"),
                ("Turkey lettuce wraps", "Light meal with plenty of protein and crunchy vegetables.", "https://www.ica.se/recept/?q=turkey%20lettuce%20wraps"),
            ],
            [
                ("Bean chili with salad", "Fiber and protein that make it easier to stay full.", "https://www.ica.se/recept/?q=bean%20chili%20salad"),
                ("Shrimp bowl with cauliflower rice", "Light but satisfying meal with lean protein.", "https://www.ica.se/recept/?q=shrimp%20cauliflower%20rice"),
                ("Chicken vegetable tray bake", "Simple portions and easy leftovers for the next day.", "https://www.ica.se/recept/?q=chicken%20vegetable%20tray%20bake"),
                ("Greek salad with grilled chicken", "Fresh, protein-forward meal for a calorie-aware routine.", "https://www.ica.se/recept/?q=greek%20salad%20chicken"),
                ("Skyr with berries and nuts", "Simple breakfast or snack with protein and controlled portions.", "https://www.ica.se/recept/?q=skyr%20berries%20nuts"),
            ],
        ],
        "aktiv": [
            [
                ("Omelet with vegetables", "Quick protein-rich meal for everyday recovery.", "https://www.ica.se/recept/?q=omelet%20vegetables"),
                ("Salmon or chicken with roasted root vegetables", "Balanced plate for energy, health, and regular training.", "https://www.ica.se/recept/?q=salmon%20root%20vegetables"),
                ("Vegetarian bean stew", "Fiber, protein, and solid everyday food for an active lifestyle.", "https://www.ica.se/recept/?q=vegetarian%20bean%20stew"),
                ("Chicken pita with yogurt sauce", "Balanced everyday meal with protein, vegetables, and carbohydrates.", "https://www.ica.se/recept/?q=chicken%20pita%20yogurt%20sauce"),
                ("Tofu noodle bowl", "Plant-based meal with energy for mixed training.", "https://www.ica.se/recept/?q=tofu%20noodle%20bowl"),
            ],
            [
                ("Turkey meatballs with tomato sauce", "A practical protein-rich dinner for regular training weeks.", "https://www.ica.se/recept/?q=turkey%20meatballs%20tomato"),
                ("Halloumi salad with quinoa", "Good mix of protein, texture, and slow carbohydrates.", "https://www.ica.se/recept/?q=halloumi%20salad%20quinoa"),
                ("Chicken noodle soup", "Light, warm meal that supports recovery and routine.", "https://www.ica.se/recept/?q=chicken%20noodle%20soup"),
                ("Egg and avocado toast", "Fast meal with protein and healthy fats.", "https://www.ica.se/recept/?q=egg%20avocado%20toast"),
                ("Chickpea curry with rice", "Fiber, steady energy, and easy leftovers.", "https://www.ica.se/recept/?q=chickpea%20curry%20rice"),
            ],
        ],
    }
    variants = recipe_sets.get(track_id, recipe_sets["aktiv"])
    return variants[variant % len(variants)]


def recipe_search_url(title: str) -> str:
    return "https://www.google.com/search?" + urlencode({"btnI": "1", "q": f"{title} recipe"})


def recipe_site_result_url(title: str, site: str) -> str:
    return "https://www.google.com/search?" + urlencode({"btnI": "1", "q": f"site:{site} {title} recipe"})


def recipe_source_links(title: str, primary_url: str) -> list[tuple[str, str]]:
    return [
        ("Best match", recipe_search_url(title)),
        ("Primary source", primary_url),
        ("ICA", recipe_site_result_url(title, "ica.se/recept")),
        ("Koket", recipe_site_result_url(title, "koket.se")),
        ("Allrecipes", recipe_site_result_url(title, "allrecipes.com")),
        ("BBC Good Food", recipe_site_result_url(title, "bbcgoodfood.com")),
    ]
