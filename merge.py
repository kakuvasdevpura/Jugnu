name: Debug Update Kaku Playlist

on:
  workflow_dispatch:
  schedule:
    - cron: "*/15 * * * *"

permissions:
  contents: write

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repo (full)
        uses: actions/checkout@v4
        with:
          fetch-depth: 0
          persist-credentials: true

      - name: Show repo info (debug)
        run: |
          echo "GitHub repository: $GITHUB_REPOSITORY"
          echo "Ref: $GITHUB_REF"
          echo "Ref name: $GITHUB_REF_NAME"
          git status --porcelain
          git rev-parse --abbrev-ref HEAD || true
          ls -la

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: "3.x"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install requests

      - name: Run merge.py (capture output)
        run: |
          python merge.py 2>&1 | tee merge_stdout.txt
        continue-on-error: false

      - name: Show output directory (debug)
        run: |
          echo "OUTPUT DIR LISTING:"
          ls -la output || true
          echo "kaku.m3u head (if exists):"
          if [ -f output/kaku.m3u ]; then head -n 40 output/kaku.m3u; else echo "NO FILE"; fi
          echo "merge_log tail:"
          if [ -f output/merge_log.txt ]; then tail -n 50 output/merge_log.txt; else echo "NO LOG"; fi

      - name: Upload debug artifacts (kaku + logs)
        uses: actions/upload-artifact@v4
        with:
          name: merge-debug-artifacts
          path: |
            merge_stdout.txt
            output/kaku.m3u
            output/merge_log.txt

      - name: Commit ONLY kaku.m3u (force add)
        run: |
          git config --local user.email "action@github.com"
          git config --local user.name "GitHub Action"
          # show gitignore
          echo "---- .gitignore ----"
          [ -f .gitignore ] && cat .gitignore || echo "(no .gitignore)"
          echo "Adding kaku.m3u"
          git add -f output/kaku.m3u || true
          if git diff --cached --quiet; then
            echo "No staged changes to commit"
          else
            git commit -m "Auto update kaku.m3u (workflow)" || echo "Commit failed"
            git --no-pager log -n 3 --pretty=oneline || true
          fi

      - name: Push changes (debug)
        env:
          TOKEN: ${{ secrets.GITHUB_TOKEN }}
          REPO: ${{ github.repository }}
        run: |
          git remote set-url origin https://x-access-token:${TOKEN}@github.com/${REPO}.git
          git fetch origin --depth=1 || true
          git push https://x-access-token:${TOKEN}@github.com/${REPO}.git HEAD:${GITHUB_REF_NAME} || (echo "Push failed" && git status --porcelain && git log -n 5 --pretty=oneline)
