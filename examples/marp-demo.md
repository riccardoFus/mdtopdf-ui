---
marp: true
size: 16:9
theme: default
paginate: true
---

<!-- _class: lead -->
<!-- _paginate: false -->

# MD → PDF Studio

### Presentazioni Marp, in locale

**Mermaid · LaTeX · PDF 16:9**

---

## Diagrammi nelle slide

```mermaid
flowchart LR
  MD[Markdown] --> M[Marp]
  M --> P[PDF 16:9]
  MD --> D[Mermaid]
  D --> P
```

- slide separate da `---`
- diagrammi Mermaid renderizzati in locale
- paginazione automatica

---

## Formule e contenuti

La formula di Einstein è $E = mc^2$.

$$
\int_0^\infty e^{-x^2}\,dx = \frac{\sqrt{\pi}}{2}
$$

> Esporta in PDF: una slide per pagina.
