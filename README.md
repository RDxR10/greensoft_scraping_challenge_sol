# Greensoft Scraping Challenge – Solution

This repo contains two scripts that present different approaches to solving Greensoft's scraping challenge. I took around 3 hours developing `sol_23_07_2025.py` and submitted it early. If there were no connectivity issues, the script typically ran quickly.

The solution was accepted, nevertheless, even though minor issues existed. 

After submission, they included a JS challenge (not sure when). This meant some alternate methods were needed because the requests started failing, and I couldn't fetch the content.

Downloading the HTML was never the issue; it was the PDF and the XML. The second script, `sol_new_proof.py` (playwright-based) is a proof solution with the PDF and XML parts completed (sanity check). Since the main script (not included in this repo) processes a large number of files, I’m not sure how long the script will take to run.

PS: Ignore the directory structure in this repo

## How to Run (Quick Check)

Once the necessary libraries are installed via ```pip install```,

Run:

``` 
python3 sol_new_proof.py
```

![Screenshot 2025-12-29 214158](https://github.com/user-attachments/assets/be70768a-2f16-4c86-bbc1-e93f587204a1)
