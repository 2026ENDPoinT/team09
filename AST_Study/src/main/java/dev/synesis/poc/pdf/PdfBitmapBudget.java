package dev.synesis.poc.pdf;

import java.util.*;
import java.util.function.IntToLongFunction;

/** Bound optional page prefetch by bytes, while always retaining pages the person can see. */
final class PdfBitmapBudget {
    static final long BYTES=Math.min(64L<<20,Math.max(16L<<20,Runtime.getRuntime().maxMemory()/32));
    private PdfBitmapBudget() {}
    static Set<Integer> select(Collection<Integer> ordered,Set<Integer> visible,IntToLongFunction cost,long budget) {
        Set<Integer> selected=new LinkedHashSet<>();long remaining=Math.max(0,budget);
        for(int page:ordered)if(visible.contains(page)) {
            selected.add(page);remaining=Math.max(0,remaining-Math.max(1,cost.applyAsLong(page)));
        }
        for(int page:ordered)if(!selected.contains(page)) {
            long bytes=Math.max(1,cost.applyAsLong(page));
            if(bytes<=remaining){selected.add(page);remaining-=bytes;}
        }
        return selected;
    }
}
