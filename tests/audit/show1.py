import json,io,sys
sys.stdout.reconfigure(encoding="utf-8",errors="replace")
d=json.load(sys.stdin)
for T,r in d.items():
    print('='*18,'T =',T,'='*18)
    f=r['fidelity']
    print('  stmt verbatim in full_code:',f['stmt_verbatim_in_full_code'],'/',r['n_traces'],' missing:',f['stmt_missing'])
    print('  decl counts:',f['decl_counts'],' multi_decl:',f['multi_decl'][:20],' no_full_code:',f['no_full_code'])
    print('  escape hatches:',{k:(len(v),v[:12]) for k,v in r['escape_hatches'].items()})
    print('  hatches comment-only:',{k:len(v) for k,v in r['escape_hatches_comment_only'].items()})
    print('  model set_options:',r['model_added_set_options'])
    t=r['truncation']
    print('  truncated:',t['truncated_true'],'-> ',t['outcome_of_truncated'])
    print('  hit_token_limit:',t['hit_token_limit'],'-> ',t['outcome_of_token_limited'])
    print('  closed_fence False:',t['closed_fence_false'],' stopped_on_eos False:',t['stopped_on_eos_false'])
    print('  extract_status:',t['extract_status'])
    print('  tokens:',r['tokens'])
    print('  timing:',r['timing'])
    print('  modes:',r['modes'])
    print('  outcomes:',r['outcomes'])
