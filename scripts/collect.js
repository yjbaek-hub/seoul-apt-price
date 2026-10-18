// 국토교통부 아파트 매매 실거래가 수집: 서울 25개 자치구 × 2021.09~2026.08
// 실행: node --env-file=.env scripts/collect.js   (seoul-apt-rate 폴더에서)
const fs = require("fs");
const path = require("path");

const KEY = process.env.DATA_GO_KR_KEY;
if (!KEY) throw new Error("DATA_GO_KR_KEY가 없습니다 (.env 확인)");

const GU = {
  11110: "종로구", 11140: "중구", 11170: "용산구", 11200: "성동구", 11215: "광진구",
  11230: "동대문구", 11260: "중랑구", 11290: "성북구", 11305: "강북구", 11320: "도봉구",
  11350: "노원구", 11380: "은평구", 11410: "서대문구", 11440: "마포구", 11470: "양천구",
  11500: "강서구", 11530: "구로구", 11545: "금천구", 11560: "영등포구", 11590: "동작구",
  11620: "관악구", 11650: "서초구", 11680: "강남구", 11710: "송파구", 11740: "강동구",
};

const months = [];
for (let y = 2021, m = 9; y < 2026 || (y === 2026 && m <= 8); m === 12 ? (y++, m = 1) : m++) {
  months.push(`${y}${String(m).padStart(2, "0")}`);
}

const RAW_DIR = path.join(__dirname, "..", "data", "raw");
fs.mkdirSync(RAW_DIR, { recursive: true });

const FIELDS = ["aptNm", "aptDong", "umdNm", "jibun", "sggCd", "dealYear", "dealMonth", "dealDay",
  "dealAmount", "excluUseAr", "floor", "buildYear", "cdealType", "cdealDay", "dealingGbn", "buyerGbn", "slerGbn"];

function parseItems(xml) {
  return [...xml.matchAll(/<item>([\s\S]*?)<\/item>/g)].map(([, body]) => {
    const row = {};
    for (const f of FIELDS) {
      const m = body.match(new RegExp(`<${f}>([\\s\\S]*?)</${f}>`));
      row[f] = m ? m[1].trim() : "";
    }
    return row;
  });
}

async function fetchMonth(sgg, ym) {
  const out = path.join(RAW_DIR, `${sgg}_${ym}.json`);
  if (fs.existsSync(out)) return JSON.parse(fs.readFileSync(out, "utf8")).length;

  const rows = [];
  for (let page = 1; ; page++) {
    const url = `https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade` +
      `?serviceKey=${KEY}&LAWD_CD=${sgg}&DEAL_YMD=${ym}&pageNo=${page}&numOfRows=1000`;
    let xml;
    for (let attempt = 1; ; attempt++) {
      try {
        const res = await fetch(url);
        xml = await res.text();
        if (!xml.includes("<resultCode>000</resultCode>")) throw new Error(xml.slice(0, 200));
        break;
      } catch (e) {
        if (attempt >= 8) throw new Error(`${sgg} ${ym} p${page}: ${e.message}`);
        await new Promise(r => setTimeout(r, 2000 * attempt));
      }
    }
    rows.push(...parseItems(xml));
    const total = Number((xml.match(/<totalCount>(\d+)<\/totalCount>/) || [])[1] || 0);
    if (rows.length >= total) break;
  }
  fs.writeFileSync(out, JSON.stringify(rows));
  return rows.length;
}

(async () => {
  const jobs = [];
  for (const sgg of Object.keys(GU)) for (const ym of months) jobs.push([sgg, ym]);
  let done = 0, total = 0;
  const CONCURRENCY = 2;
  async function worker() {
    while (jobs.length) {
      const [sgg, ym] = jobs.shift();
      const n = await fetchMonth(sgg, ym); // `total += await ...`는 병렬 워커끼리 값을 덮어씀
      total += n;
      await new Promise(r => setTimeout(r, 250));
      if (++done % 100 === 0) console.log(`${done}/${25 * months.length} 완료, 누적 ${total}건`);
    }
  }
  await Promise.all(Array.from({ length: CONCURRENCY }, worker));
  console.log(`끝: ${done}개 요청, ${total}건`);
})().catch(e => { console.error(e.message); process.exit(1); });
