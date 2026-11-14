package dev.synesis.poc.pdf;

import java.util.*;

public final class PdfBitmapBudgetTest {
    public static void main(String[] args) {
        List<Integer> pages=List.of(3,4,5,2,1);
        check(PdfBitmapBudget.select(pages,Set.of(3),n->20,64).equals(new LinkedHashSet<>(List.of(3,4,5))),"prefetch follows movement direction within the byte budget");
        check(PdfBitmapBudget.select(pages,Set.of(3,4),n->40,64).equals(Set.of(3,4)),"both visible pages survive even when their combined size exceeds the optional budget");
        check(PdfBitmapBudget.select(pages,Set.of(3),n->n==4?1000:10,32).equals(new LinkedHashSet<>(List.of(3,5,2))),"an oversized optional image does not crowd out smaller nearby pages");
        check(PdfBitmapBudget.select(pages,Set.of(3),n->10,0).equals(Set.of(3)),"a small heap still renders the current page at full quality");
        check(PdfBitmapBudget.select(pages,Set.of(3),n->Long.MAX_VALUE,64).equals(Set.of(3)),"large estimates never wrap the budget");
        check(PdfBitmapBudget.BYTES>=16L<<20&&PdfBitmapBudget.BYTES<=64L<<20,"runtime budget stays bounded for low-memory and high-memory devices");
        System.out.println("PASS: byte-limited prefetch, visible-page priority, direction, oversized images and bounded heap policy");
    }
    static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
}
