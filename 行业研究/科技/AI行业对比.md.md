# AI 行业财报对比  
  
## 最新一期核心指标  
  
```dataview  
TABLE   
  代码,  
  财年, 季度,  
  营业收入 AS "收入(亿)",  
  净利润 AS "净利(亿)",  
  CapEx AS "资本开支(亿)",  
  ROE AS "ROE"  
FROM #财报 AND #科技  
WHERE 财年 = "FY2026"  
SORT 营业收入 DESC  
```  
  
## 近八季营收趋势  
  
```dataview  
TABLE 公司, 财年, 季度, 营业收入, 营收同比  
FROM #财报 AND #科技  
SORT 公司 ASC, 财年 DESC, 季度 DESC  
LIMIT 32  
```  
  
## CapEx 高投入筛选（资本开支同比增速 > 30%）  
  
```dataview  
TABLE 公司, 财年, 季度, CapEx, 净利率  
FROM #财报 AND #科技  
WHERE CapEx同比 > 30  
SORT CapEx DESC  
```