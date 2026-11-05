#!/usr/bin/env bash
# گزارشِ شکستِ یک گامِ CI: اولِ کار «چهی خطا» را به Annotation و Step Summary می‌فرسته.
# استفاده: bash scripts/ci_fail_report.sh "نامِ گام" logs/x.log
#
# چرا این‌شکل: اولین شکستِ عمومیِ CI فقط «Process completed with exit code 2» نشان می‌داد و
# ته‌ِ لاگ هم فقط ردیفِ نقطه‌ی پیشرفتِ pytest بود (%%)؛ یعنی هیچ‌کس نمی‌دانست کدام تست افتاده.
# حالا خط‌های «FAILED …» / «ERROR …» اگر باشند، اولِ پیام میان (و بعد ته‌ِ لاگ)، تا از صفحه‌ی
# Actions بدونِ باز کردنِ لاگِ کامل یا دانلودِ Artifact معلوم باشد علت کجاست.
set -u
step="${1:-step}"
log="${2:-/dev/null}"

# خلاصه‌ی خطاها: خط‌های FAILED/ERROR + خطِ پایانیِ «X failed / Y passed»
fails="$(grep -aE '^(FAILED|ERROR)' "$log" 2>/dev/null | head -n 12 | tr -d '\r')"
count="$(grep -acE '^(FAILED|ERROR)' "$log" 2>/dev/null | tr -d '\r')"
summary="$(grep -aE '=(.*(passed|failed|error).*=( *=|$))' "$log" 2>/dev/null | tail -n 1 | tr -d '\r')"
tail_text="$(tail -n 25 "$log" 2>/dev/null | tr -d '\r' | tr '\n' ' ' | cut -c1-900)"

one_line="${fails//$'\n'/ | }"
one_line="${one_line//%/%25}"
[ -n "$one_line" ] || one_line="(هیچ خطِ FAILED/ERROR در لاگ پیدا نشد) … ${tail_text}"
[ -n "$summary" ] && one_line="$one_line ⟵ $summary"

echo "::error title=${step} failed::${one_line:0:1500}"

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "### ❌ ${step} failed (${RUNNER_OS:-?})"
    if [ -n "$fails" ]; then
      echo "**${count} خطِ FAILED/ERROR:**"
      echo '```'
      echo "$fails"
      echo '```'
    fi
    [ -n "$summary" ] && echo "**خلاصه:** \`$summary\`"
    echo '<details><summary>ته‌ِ لاگ</summary>'
    echo ""
    echo '```'
    tail -n 80 "$log" 2>/dev/null | tr -d '\r'
    echo '```'
    echo ""
    echo "</details>"
  } >> "$GITHUB_STEP_SUMMARY"
fi
