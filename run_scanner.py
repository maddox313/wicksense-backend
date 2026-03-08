from app import scan_markets

if __name__ == "__main__":
    results = scan_markets()
    print({"status": "scan completed", "results": results})
