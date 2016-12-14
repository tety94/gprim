from __future__ import print_function, division
import os, gzip
import numpy as np
import pandas as pd
import itertools
from pyutils import memo, fs


# complementary bases
COMPLEMENT = {'A': 'T', 'T': 'A', 'C': 'G', 'G': 'C'}
# bases
BASES = COMPLEMENT.keys()
# true iff strand ambiguous
STRAND_AMBIGUOUS = {''.join(x): x[0] == COMPLEMENT[x[1]]
        for x in itertools.product(BASES, BASES)
        if x[0] != x[1]}
# SNPS we want to keep (pairs of alleles)
VALID_SNPS = {x for x in map(lambda y: ''.join(y), itertools.product(BASES, BASES))
        if x[0] != x[1] and not STRAND_AMBIGUOUS[x]}
# T iff SNP 1 has the same alleles as SNP 2 (allowing for strand or ref allele flip)
# and neither is invalid.
MATCH_ALLELES = {
        x for x in map(lambda y: ''.join(y), itertools.product(VALID_SNPS, VALID_SNPS))
        # strand and ref match
        if ((x[0] == x[2]) and (x[1] == x[3])) or
        # ref match, strand flip
        ((x[0] == COMPLEMENT[x[2]]) and (x[1] == COMPLEMENT[x[3]])) or
        # ref flip, strand match
        ((x[0] == x[3]) and (x[1] == x[2])) or
        # ref flip, strand flip
        ((x[0] == COMPLEMENT[x[3]]) and (x[1] == COMPLEMENT[x[2]]))}
# T iff SNP 1 has the same alleles as SNP 2 w/ ref allele flip and neither is invalid
FLIP_ALLELES = {x for x in MATCH_ALLELES
        # ref flip, strand match
        if ((x[0] == x[3]) and (x[1] == x[2])) or
        # ref flip, strand flip
        ((x[0] == COMPLEMENT[x[3]]) and (x[1] == COMPLEMENT[x[2]]))}

# Checks if SNP columns are equal. If so, saves time by using concat instead of merge.
# y can be either a single df or a list of dfs
# if x is a list, then y is unnecessary
def smart_merge(x, y=[], how='inner', fail_if_nonmatching=False, drop_from_y=[], key='SNP'):
    # make y into a list if it's just a single df
    if type(y) == pd.DataFrame:
        y = [y]
    # if x is a list, pass the rest onto y
    if type(x) != pd.DataFrame: # assume x is a list
        y = x[1:] + y
        x = x[0]

    # drop uninteresting columns from y and check that snps match
    matching = True
    for d in y:
        d.drop(drop_from_y, axis=1, inplace=True)
        if len(x) != len(d) or (x[key] != d[key]).any():
            matching = False

    x = x.reset_index(drop=True)
    if matching:
        return pd.concat([x]+[d.reset_index(drop=True).drop(key, axis=1) for d in y],
                axis=1)
    else:
        if fail_if_nonmatching:
            print('smart_merge sees that the dataframs dont have same snps in same order')
            exit()
        else:
            for d in y:
                x = pd.merge(x,
                        d.reset_index(drop=True), how=how, on=key)
        return x

# keeps only snps in ref, flips alleles in df to match those in ref, and sets value at
# non-matching snps to a missing_val (0 by default). 
# ref must contain: SNP, A1, A2
# df must contain: SNP, A1, A2, and colnames
def reconciled_to(ref, df, colnames, othercolnames=[], signed=True, missing_val=0, key='SNP'):
    result = smart_merge(
        ref,
        df[[key,'A1','A2']+list(colnames)+othercolnames].rename(
            columns={'A1':'A1_df','A2':'A2_df'}),
        how='left',
        key=key)
    print(len(result), 'snps after merging')
    if len(result) != len(ref):
        print('WARNING: merged data frame is not the same length as reference data frame')
        print('   check for duplicate snps in one of the two dataframes')

    # snps in ref but not in df
    missing = result.A1_df.isnull()
    print('of', len(result), 'snps in merge,', missing.sum(), 'were missing in df')
    result.loc[missing,colnames] = missing_val
    result.loc[missing,'A1_df'] = result.loc[missing,'A2_df'] = '-'

    # snps in both, but either invalid or not matching
    a1234 = (result.A1+result.A2+result.A1_df+result.A2_df).apply(lambda y: y.upper())
    match = ~missing & a1234.apply(lambda y: y in MATCH_ALLELES)
    n_mismatch = (~missing & ~match).sum()
    print('of', (~missing).sum(), 'remaining snps,', n_mismatch,
            'are a) present in ref and df, b) do not have matching sets of alleles '+\
                    'that are both valid,')
    result.loc[~missing & ~match,colnames] = missing_val

    if signed:
        flip = match & a1234.apply(lambda y: y in FLIP_ALLELES)
        n_flip = flip.sum()
        print('of the remaining', match.sum(), 'snps,', n_flip, 'snps need flipping',
            'and', (match & ~flip).sum(), 'snps matched and did not need flipping')
        result.loc[flip,colnames] *= -1

    return result.drop(['A1_df', 'A2_df'], axis=1)


class Annotation(object):
    def __init__(self, stem_chr, signed=True):
        self.stem_chr = stem_chr
        self.signed = signed

    def filestem(self, chrnum='', mkdir=False):
        fname = '{}{}'.format(self.stem_chr, chrnum)
        if mkdir:
            fs.makedir_for_file(fname)
        return fname
    def annot_filename(self, chrnum):
        return self.filestem(chrnum) + '.annot.gz'
    def sannot_filename(self, chrnum, mkdir=False):
        return self.filestem(chrnum, mkdir) + '.sannot.gz'
    def sqnorm_filename(self, chrnum):
        return self.filestem(chrnum) + '.sqnorm'
    def size_filename(self, chrnum):
        return self.filestem(chrnum) + '.M'
    def ldscores_filename(self, chrnum):
        return self.filestem(chrnum) + '.l2.ldscore.gz'
    def conv_filename(self, chrnum, full=False):
        if not full:
            return self.filestem(chrnum) + '.conv.gz'
        else:
            return self.filestem(chrnum) + '.fullconv.gz'
    @classmethod
    def isfullconv(cls, filename):
        return filename.endswith('.fullconv.gz')

    @memo.memoized
    def annot_df(self, chrnum):
        return pd.read_csv(self.annot_filename(chrnum),
                compression='gzip', header=0, sep='\t')
    def sannot_df(self, chrnum):
        return pd.read_csv(self.sannot_filename(chrnum),
                compression='gzip', header=0, sep='\t')
    @memo.memoized
    def sqnorms(self, chrnum):
        return pd.read_csv(self.sqnorm_filename(chrnum), names=self.names(chrnum), sep='\t')
    @memo.memoized
    def sizes(self, chrnum):
        return pd.read_csv(self.size_filename(chrnum), names=self.names(chrnum), sep='\t')

    @memo.memoized
    def names(self, chrnum):
        if os.path.exists(self.annot_filename(chrnum)):
            fname = self.annot_filename(chrnum)
            with gzip.open(fname, 'r') as f:
                line = f.readline().strip().split('\t')
            return line[4:]
        else: # assuming sannot exists
            fname = self.sannot_filename(chrnum)
            with gzip.open(fname, 'r') as f:
                line = f.readline().strip().split('\t')
            return line[6:]
    @classmethod
    def names_observed(cls, names):
        return [n + '.O' for n in names]
    @classmethod
    def names_conv(cls, names, observed=True):
        O = ('.O' if observed else '')
        return [n + O + '.conv' for n in names]

    @memo.memoized
    def num_snps(self, chrnum):
        if os.path.exists(self.annot_filename(chrnum)):
            return len(self.annot_df(chrnum))
        else: # assuming sannot exists
            return len(self.sannot_df(chrnum))

    def total_sqnorms(self, chromosomes):
        return sum([self.sqnorms(c) for c in chromosomes])
    def total_sizes(self, chromosomes):
        return sum([self.sizes(c) for c in chromosomes])


if __name__ == '__main__':
    a = Annotation('/groups/price/yakir/data/simannot/1000G3.wim5unm/mock/')
    print(a.names(22))
    print(a.sannot_df(22))
    print(a.sqnorms(22))
    print(a.sizes(22))
    print(a.total_sqnorms([1,22]))
    print(a.total_sizes([1,22]))

    ref = pd.read_csv('/groups/price/yakir/data/simannot/1000G3.wim5unm/mock/22.sannot.gz',
            delimiter='\t').drop('ANNOT', axis=1).iloc[:20]

    ref.ix[0,'A1'] = a.sannot_df(22).ix[0,'A2']
    ref.ix[0,'A2'] = a.sannot_df(22).ix[0,'A1']
    ref.ix[1,'A1'] = 'A'; ref.ix[1,'A2'] = 'C'
    print(ref)

    print(reconciled_to(ref, a.sannot_df(22), ['ANNOT']))
