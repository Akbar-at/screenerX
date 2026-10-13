"""Evidence-based Indonesian research narratives and shareable PNG/PDF reports."""
import argparse
import json
import math
import textwrap
import threading
from pathlib import Path

from .engine import InputError, load_prices
from .fetch import symbol_for

RENDER_LOCK = threading.Lock()
GREEN = '#176148'
INK = '#19352e'
MUTED = '#61726b'
RED = '#ba493e'


def money(value):
    return 'belum tersedia' if value is None else 'Rp' + f'{value:,.0f}'.replace(',', '.')


def percent(value):
    return 'belum tersedia' if value is None else f'{value:.1%}'


def recommendation(company):
    technical=company.get('technical') or {}
    plan=company.get('plan') or {}
    if not company.get('coverage_complete'):
        return 'DATA BELUM LENGKAP', 'Lengkapi data sebelum mempertimbangkan entry.'
    if not company.get('quality_passed'):
        return 'KAJIAN LANJUTAN', 'Kandidat belum lolos pemeriksaan kualitas; jangan memakai estimasi sebagai dasar entry.'
    if plan.get('net_rr') is None or not company.get('execution_readiness',{}).get('reward_risk_passed'):
        return 'TUNGGU SETUP BARU', 'Lewatkan rencana entry ini; imbalan terhadap risiko setelah biaya belum memenuhi minimum profil.'
    close=company.get('close')
    trend=(close is not None and close > technical.get('sma20', math.inf)
           and technical.get('sma20',0)>technical.get('sma60',math.inf)
           and technical.get('macd',0)>technical.get('macd_signal',math.inf))
    if not trend:
        return 'TUNGGU KONFIRMASI', 'Pantau pemulihan tren dan konfirmasi harga; belum ada konfirmasi entry dari kondisi saat ini.'
    return 'PANTAU BREAKOUT', 'Pantau penembusan level entry dengan volume; rencana tetap bersyarat dan memerlukan pemeriksaan data serta eksekusi.'


def narrative(company):
    ticker=company['ticker']; close=company.get('close'); t=company.get('technical') or {}
    v=company.get('valuation') or {}; plan=company.get('plan') or {}
    label,action=recommendation(company)
    sections=[]
    if t and close is not None and all(t.get(k) is not None for k in ('sma20','sma60','macd','macd_signal','rsi','stoch_k','stoch_d','volume_multiple')):
        relation='di atas' if close>t['sma20'] else 'di bawah atau sama dengan'
        trend='menguat' if t['sma20']>t['sma60'] else 'belum menguat'
        momentum='di atas' if t['macd']>t['macd_signal'] else 'di bawah atau sama dengan'
        sections.append(('Teknikal & struktur harga',
            f"{ticker} ditutup pada {money(close)}, {relation} SMA20 {money(t['sma20'])}. "
            f"SMA20 dibanding SMA60 {money(t['sma60'])} menunjukkan tren {trend}. "
            f"MACD {t['macd']:.2f} berada {momentum} signal {t['macd_signal']:.2f}; "
            f"RSI {t['rsi']:.1f}, stochastic K/D {t['stoch_k']:.1f}/{t['stoch_d']:.1f}, "
            f"dan volume {t['volume_multiple']:.2f}x median sebelumnya. "
            f"Support/resistance rolling: {money(plan.get('support'))} / {money(plan.get('resistance'))}."))
    else:
        sections.append(('Teknikal & struktur harga','Riwayat harga/indikator belum memadai untuk analisis teknikal yang lengkap.'))
    if v:
        methods=', '.join(f'{m.upper()} {money(v[m])}' for m in ('ddm','rim','eva') if v.get(m) is not None)
        sections.append(('Fundamental & valuasi',
            f"Laporan tahunan {v['statement_date']} dari {v['financial_provider']}: {methods or 'model belum tersedia'}. "
            f"Rata-rata model {money(v.get('fair_value'))}; margin of safety {percent(v.get('current_mos'))}; "
            f"dispersi {percent(v.get('dispersion'))}. Skenario bear/base/bull: "
            f"{money(v.get('bear_value'))} / {money(v.get('fair_value'))} / {money(v.get('bull_value'))}. "
            'Ini estimasi dengan asumsi pertumbuhan dan tingkat diskonto, bukan target harga yang dijamin.'))
    else:
        reasons='; '.join(x['reason'] for x in company.get('missing_inputs',[]) if x['check'] in ('aligned_financials','financial_evidence'))
        sections.append(('Fundamental & valuasi','Valuasi belum tersedia. '+(reasons or 'Data laporan keuangan yang cocok belum tersedia.')))
    sections.append(('Broker flow', 'ON_HOLD. Data transaksi broker belum terintegrasi; akumulasi/distribusi asing atau institusi belum dapat dikonfirmasi.'))
    rr=plan.get('net_rr')
    sections.append(('Strategi & invalidasi',
        action+' '+f"Level indikatif entry {money(plan.get('entry_price'))}, TP1 {money(plan.get('tp1_price'))}, "
        f"TP2 {money(plan.get('tp2_price'))}, stop {money(plan.get('stop_loss_price'))}. "
        f"Net R/R {f'{rr:.2f}x' if rr is not None else 'belum tersedia'}. "
        'Level dihitung dari OHLC historis dan perlu dihitung ulang jika harga berubah. '
        'Rencana gugur jika harga melewati stop; level ini bukan bukti bahwa entry telah terjadi.'))
    issues=company.get('failed_quality_checks',[])+company.get('missing_inputs',[])
    risks=[x['reason'] for x in issues][:3]+plan.get('risk_reasons',[])[:2]
    risks+=['Valuasi belum direview; corporate actions dan bid/offer belum diverifikasi.']
    sections.append(('Risiko utama',' '.join(dict.fromkeys(risks))))
    return {'ticker':ticker,'as_of':company['as_of'],'label':label,'action':action,'sections':sections,
            'text':f"{ticker} | {company['as_of']} | {label}\n\n"+'\n\n'.join(title+'\n'+body for title,body in sections)}


class ReportRepository:
    def __init__(self,run_dir,prices_path):
        self.run_dir=Path(run_dir)
        self.report=json.loads((self.run_dir/'core-run.json').read_text(encoding='utf-8'))
        self.companies={x['ticker']:x for x in self.report['companies']}
        self.prices=load_prices(prices_path)
        self.prices_path=Path(prices_path)

    def company(self,ticker):
        ticker,_=symbol_for(ticker)
        if ticker not in self.companies: raise InputError(f'{ticker} belum ada di run ini; gunakan /stock {ticker} live jika live lookup diaktifkan.')
        return self.companies[ticker]

    def bars(self,ticker):
        asof=self.report['as_of']
        return [r for r in self.prices.get(ticker,[]) if r['date'].isoformat()<=asof]


def figure(company,bars):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    from matplotlib.ticker import FuncFormatter
    fig=plt.figure(figsize=(10,14),facecolor='white')
    info=narrative(company); t=company.get('technical') or {}; v=company.get('valuation') or {}; plan=company.get('plan') or {}
    fig.text(.06,.967,'screenerX',fontsize=22,fontweight='bold',color=GREEN)
    fig.text(.94,.973,'RISET SAHAM INDONESIA',ha='right',fontsize=10,color=MUTED)
    fig.text(.94,.955,company['as_of']+'  |  Yahoo / yfinance',ha='right',fontsize=9,color=MUTED)
    fig.text(.06,.922,company['ticker']+'  |  '+money(company.get('close')),fontsize=24,fontweight='bold',color=INK)
    fig.text(.06,.899,info['label'],fontsize=12,fontweight='bold',color=RED if 'TUNGGU' in info['label'] else GREEN)
    score=company.get('score')
    fig.text(.94,.922,f"Skor riset {score['total']:.1f}/100" if score else 'Tidak masuk ranking',ha='right',fontsize=12,color=INK)
    ax=fig.add_axes([.075,.637,.61,.235]); volume=fig.add_axes([.075,.589,.61,.04],sharex=ax)
    view=bars[-90:]; ax.set_facecolor('#f6f9f7')
    if view:
        for i,b in enumerate(view):
            color=GREEN if b['close']>=b['open'] else RED
            ax.plot([i,i],[b['low'],b['high']],color=color,linewidth=.8)
            height=max(abs(b['close']-b['open']),b['close']*.0005)
            ax.add_patch(Rectangle((i-.3,min(b['open'],b['close'])),.6,height,facecolor=color,edgecolor=color,linewidth=.5))
            volume.bar(i,b['volume'],color=color,width=.7)
        offset=len(bars)-len(view)
        for period,color in ((20,'#d49723'),(60,'#687eab')):
            means=[sum(b['close'] for b in bars[max(0,j-period+1):j+1])/period if j>=period-1 else None for j in range(offset,len(bars))]
            ax.plot(range(len(view)),means,color=color,linewidth=1.2,label=f'SMA{period}')
        for key,label,color in (('entry_price','Entry',GREEN),('stop_loss_price','Stop',RED),('tp1_price','TP1','#5668a2')):
            value=plan.get(key)
            lo=min(b['low'] for b in view); hi=max(b['high'] for b in view)
            if value is not None and lo*.9<=value<=hi*1.1:
                ax.axhline(value,color=color,linestyle='--',linewidth=.8,label=f'{label} {value:,.0f}')
        marks=list(range(0,len(view),max(1,len(view)//5)))
        volume.set_xticks(marks,[view[i]['date'].strftime('%d/%m') for i in marks],fontsize=8)
        ax.legend(loc='upper left',fontsize=7,framealpha=.9,ncol=2)
    else:
        ax.text(.5,.5,'Riwayat harga belum tersedia',transform=ax.transAxes,ha='center',color=MUTED)
        ax.set_axis_off(); volume.set_axis_off()
    ax.yaxis.set_major_formatter(FuncFormatter(lambda val,pos:f'{val:,.0f}'))
    ax.tick_params(labelsize=8,labelbottom=False); ax.grid(alpha=.12)
    volume.tick_params(axis='y',left=False,labelleft=False); volume.set_ylabel('Vol',fontsize=7)
    for axis in (ax,volume):
        for spine in axis.spines.values(): spine.set_visible(False)
    x=.72; y=.858
    fig.text(x,y,'VALUASI & LEVEL',fontsize=10,fontweight='bold',color=GREEN)
    def model_label(method):
        if company.get('models',{}).get(method,{}).get('status')=='NOT_APPLICABLE': return 'Tidak berlaku'
        return money(v.get(method))
    lines=[('DDM',model_label('ddm')),('RIM',model_label('rim')),('EVA',model_label('eva')),
           ('Rata-rata',money(v.get('fair_value'))),('MOS',percent(v.get('current_mos'))),
           ('Entry',money(plan.get('entry_price'))),('TP1 / TP2',money(plan.get('tp1_price'))+' / '+money(plan.get('tp2_price'))),
           ('Stop',money(plan.get('stop_loss_price'))),('Net R/R',f"{plan['net_rr']:.2f}x" if plan.get('net_rr') is not None else 'belum tersedia')]
    for label,value in lines:
        y-=.026
        fig.text(x,y,label,fontsize=8,color=MUTED)
        fig.text(x,y-.012,value,fontsize=9,color=INK)
    y=.548
    for title,body in info['sections']:
        fig.text(.06,y,title.upper(),fontsize=9.5,fontweight='bold',color=GREEN)
        wrapped=textwrap.fill(body,width=114)
        fig.text(.06,y-.016,wrapped,fontsize=8.6,color=INK,va='top',linespacing=1.55)
        y-=.022+.0145*len(wrapped.splitlines())
    fig.text(.06,.028,'ESTIMASI BELUM DIREVIEW  |  BROKER FLOW ON_HOLD  |  RISET BERSYARAT',fontsize=8,color=RED)
    fig.text(.94,.015,'screenerX Research',ha='right',fontsize=8,color=MUTED)
    return fig


def summary_figure(report):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig=plt.figure(figsize=(10,11),facecolor='white')
    fig.text(.07,.93,'screenerX | Top 10',fontsize=26,fontweight='bold',color=GREEN)
    fig.text(.07,.892,f"Sesi {report['as_of']}  |  {report['selected_count']} kandidat lolos dari {report['universe_count']} kode",fontsize=12,color=INK)
    ax=fig.add_axes([.07,.23,.86,.60]); ax.axis('off')
    rows=[]
    for c in report['top10']:
        v=c.get('valuation') or {}
        rows.append([c['rank'],c['ticker'],f"{c['score']['total']:.1f}",money(c.get('close')),percent(v.get('current_mos')),recommendation(c)[0]])
    while len(rows)<report['requested_slots']:
        rows.append([len(rows)+1,'Belum terisi','-','-','-','Belum ada kandidat lolos'])
    table=ax.table(cellText=rows,colLabels=['Rank','Kode','Skor','Close','MOS','Sikap riset'],cellLoc='left',colLoc='left',loc='upper center',colWidths=[.07,.1,.08,.15,.10,.50])
    table.auto_set_font_size(False); table.set_fontsize(9); table.scale(1,2.8)
    for (row,col),cell in table.get_celld().items():
        cell.set_edgecolor('white')
        cell.set_facecolor(GREEN if row==0 else '#eef5f0' if row%2 else '#f8faf9')
        cell.get_text().set_color('white' if row==0 else INK)
    fig.text(.07,.18,f"{report['coverage_complete_count']} perusahaan memiliki cakupan riset lengkap. {report['unfilled_slots']} slot belum terisi.",fontsize=11,color=INK)
    fig.text(.07,.13,'Ranking riset tidak berarti sinyal beli. Periksa konfirmasi harga dan net R/R.\nValuasi belum direview; broker flow ON_HOLD.',fontsize=11,color=MUTED,linespacing=1.8)
    fig.text(.07,.045,'Data: Yahoo / yfinance | Profil fundamental 50% + teknikal 40% + likuiditas 10%',fontsize=9,color=MUTED)
    return fig


def save_chart(fig,company,bars,path):
    """Export native chart axes, including full price labels and the final session."""
    from matplotlib.transforms import Bbox
    for label in list(fig.texts): label.remove()
    fig.axes[0].set_title(f"{company['ticker']} | {company['as_of']} | Daily OHLCV",loc='left',fontsize=12,pad=12)
    view=bars[-90:]
    if view:
        marks=sorted(set(list(range(0,len(view),max(1,len(view)//5)))+[len(view)-1]))
        fig.axes[1].set_xticks(marks,[view[i]['date'].strftime('%d/%m') for i in marks],fontsize=8)
    fig.savefig(path,dpi=180,bbox_inches=Bbox.from_bounds(0,8.0,7.0,4.55),facecolor='white')


def render_stock(company,bars,output):
    import matplotlib.pyplot as plt
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    stem=f"{company['ticker']}-{company['as_of']}"
    with RENDER_LOCK:
        fig=figure(company,bars)
        fig.savefig(output/(stem+'.png'),dpi=160,facecolor='white')
        fig.savefig(output/(stem+'.pdf'),facecolor='white')
        save_chart(fig,company,bars,output/(stem+'-chart.png'))
        plt.close(fig)
    info=narrative(company)
    (output/(stem+'.txt')).write_text(info['text'],encoding='utf-8')
    return {'png':output/(stem+'.png'),'chart':output/(stem+'-chart.png'),'pdf':output/(stem+'.pdf'),'text':info['text']}


def render_top(repository,output):
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    report=repository.report; stem='top10-'+report['as_of']; analyses=[]
    with RENDER_LOCK:
        with PdfPages(output/(stem+'.pdf')) as pdf:
            fig=summary_figure(report); fig.savefig(output/(stem+'.png'),dpi=160); pdf.savefig(fig); plt.close(fig)
            for company in report['top10']:
                bars=repository.bars(company['ticker']); fig=figure(company,bars)
                pdf.savefig(fig)
                chart=output/f"{company['ticker']}-{company['as_of']}-chart.png"
                save_chart(fig,company,bars,chart); plt.close(fig)
                info=narrative(company)
                analyses.append({'ticker':company['ticker'],'chart':str(chart),'text':info['text'],'label':info['label']})
    text=f"Top 10 | {report['as_of']}\n{report['selected_count']} kandidat lolos; {report['unfilled_slots']} slot belum terisi.\n\n"
    text+='\n\n'.join(f"{c['rank']}. {c['ticker']} - skor {c['score']['total']:.1f}\n{recommendation(c)[1]}" for c in report['top10'])
    text+='\n\nValuasi belum direview. Broker flow ON_HOLD. Gunakan /stock KODE untuk kajian lengkap.'
    (output/(stem+'.txt')).write_text(text,encoding='utf-8')
    return {'png':output/(stem+'.png'),'pdf':output/(stem+'.pdf'),'text':text,'analyses':analyses}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',required=True); parser.add_argument('--prices',required=True)
    parser.add_argument('--output',required=True); parser.add_argument('--ticker')
    args=parser.parse_args(argv); repository=ReportRepository(args.run_dir,args.prices)
    artifacts=render_stock(repository.company(args.ticker),repository.bars(symbol_for(args.ticker)[0]),args.output) if args.ticker else render_top(repository,args.output)
    print(json.dumps({k:str(v) for k,v in artifacts.items() if k not in ('text','analyses')},indent=2))


if __name__=='__main__': main()
