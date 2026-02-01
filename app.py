from exa_py import Exa
import os

exa = Exa('7855902d-dd13-48fa-9ea2-105454a432dd')

while True:
    query = input("\nSearch here (or type 'quit' to exit): ")

    if query.lower() == "quit":
        print("Goodbye")
        break

    try:
        response = exa.search(
            query=query,
            num_results=3,
            type="keyword",
            include_domains=["tiktok.com"]
        )

        if not response.results:
            print("No results found.")
        else:
            for i, result in enumerate(response.results, start=1):
                print(f"\nResult {i}")
                print("-" * 40)
                print(f"Title: {result.title}")
                print(f"URL: {result.url}")

    except Exception as e:
        print("An error occurred:", e)

    again = input("\nWould you like to search again? (y/n): ").strip().lower()
    if again != "y":
        print("Goodbye")
        break
