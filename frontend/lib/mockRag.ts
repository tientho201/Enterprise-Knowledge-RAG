export interface DocumentChunk {
  id: string;
  docId: string;
  docName: string;
  title: string;
  snippet: string;
  score: number;
  article: string;
  clause?: string;
}

export interface MockDocument {
  id: string;
  name: string;
  code: string;
  uploadDate: string;
  size: string;
  description: string;
  status: 'ready' | 'processing' | 'error';
  type: 'pdf' | 'docx' | 'txt';
  chunks: Omit<DocumentChunk, 'score'>[];
}

export interface RAGStep {
  name: string;
  status: 'pending' | 'running' | 'completed';
  details?: string;
}

export interface RAGResponse {
  steps: RAGStep[];
  citations: DocumentChunk[];
  answer: string;
  processingTimeMs: number;
  tokensCount: {
    prompt: number;
    completion: number;
  };
}

export const initialDocuments: MockDocument[] = [
  {
    id: 'ldn-2020',
    name: 'Luật Doanh nghiệp 2020',
    code: '59/2020/QH14',
    uploadDate: '2026-01-10',
    size: '1.2 MB',
    description: 'Quy định về việc thành lập, tổ chức quản lý, tổ chức lại, giải thể và hoạt động có liên quan của doanh nghiệp.',
    status: 'ready',
    type: 'pdf',
    chunks: [
      {
        id: 'ldn-c1',
        docId: 'ldn-2020',
        docName: 'Luật Doanh nghiệp 2020',
        title: 'Điều 5: Tiêu chí, quyền và nghĩa vụ của doanh nghiệp xã hội',
        article: 'Điều 5',
        clause: 'Khoản 1',
        snippet: 'Doanh nghiệp xã hội phải đáp ứng các tiêu chí sau đây: a) Là doanh nghiệp được đăng ký thành lập theo quy định của Luật này; b) Mục tiêu hoạt động nhằm giải quyết vấn đề xã hội, môi trường vì lợi ích cộng đồng; c) Sử dụng ít nhất 51% tổng lợi nhuận sau thuế hằng năm của doanh nghiệp để tái đầu tư nhằm thực hiện mục tiêu xã hội, môi trường như đã đăng ký.'
      },
      {
        id: 'ldn-c2',
        docId: 'ldn-2020',
        docName: 'Luật Doanh nghiệp 2020',
        title: 'Điều 4: Giải thích từ ngữ - Người đại diện theo pháp luật',
        article: 'Điều 4',
        clause: 'Khoản 12',
        snippet: 'Người đại diện theo pháp luật của doanh nghiệp là cá nhân đại diện cho doanh nghiệp thực hiện các quyền và nghĩa vụ phát sinh từ giao dịch của doanh nghiệp, đại diện cho doanh nghiệp với tư cách người yêu cầu giải quyết việc dân sự, nguyên đơn, bị đơn, người có quyền lợi, nghĩa vụ liên quan trước Trọng tài, Tòa án và các quyền, nghĩa vụ khác theo quy định của pháp luật.'
      },
      {
        id: 'ldn-c3',
        docId: 'ldn-2020',
        docName: 'Luật Doanh nghiệp 2020',
        title: 'Điều 44: Chi nhánh, văn phòng đại diện và địa điểm kinh doanh',
        article: 'Điều 44',
        clause: 'Khoản 1, 2',
        snippet: '1. Chi nhánh là đơn vị phụ thuộc của doanh nghiệp, có nhiệm vụ thực hiện toàn bộ hoặc một phần chức năng của doanh nghiệp, bao gồm cả chức năng đại diện theo ủy quyền. Ngành, nghề kinh doanh của chi nhánh phải đúng với ngành, nghề kinh doanh của doanh nghiệp. \n2. Văn phòng đại diện là đơn vị phụ thuộc của doanh nghiệp, có nhiệm vụ đại diện theo ủy quyền cho lợi ích của doanh nghiệp và bảo vệ các lợi ích đó. Văn phòng đại diện không thực hiện chức năng kinh doanh của doanh nghiệp.'
      }
    ]
  },
  {
    id: 'blds-2015',
    name: 'Bộ luật Dân sự 2015',
    code: '91/2015/QH13',
    uploadDate: '2026-02-15',
    size: '2.8 MB',
    description: 'Quy định địa vị pháp lý, chuẩn mực pháp lý cho cách ứng xử của cá nhân, pháp nhân, các quyền, nghĩa vụ dân sự.',
    status: 'ready',
    type: 'pdf',
    chunks: [
      {
        id: 'blds-c1',
        docId: 'blds-2015',
        docName: 'Bộ luật Dân sự 2015',
        title: 'Điều 122: Giao dịch dân sự vô hiệu',
        article: 'Điều 122',
        snippet: 'Giao dịch dân sự không có một trong các điều kiện được quy định tại Điều 117 của Bộ luật này thì vô hiệu, trừ trường hợp Bộ luật này có quy định khác.'
      },
      {
        id: 'blds-c2',
        docId: 'blds-2015',
        docName: 'Bộ luật Dân sự 2015',
        title: 'Điều 117: Điều kiện có hiệu lực của giao dịch dân sự',
        article: 'Điều 117',
        clause: 'Khoản 1',
        snippet: 'Giao dịch dân sự có hiệu lực khi có đủ các điều kiện sau đây: a) Chủ thể có năng lực pháp luật dân sự, năng lực hành vi dân sự phù hợp với giao dịch dân sự được xác lập; b) Chủ thể tham gia giao dịch dân sự hoàn toàn tự nguyện; c) Mục đích và nội dung của giao dịch dân sự không vi phạm điều cấm của luật, không trái đạo đức xã hội.'
      },
      {
        id: 'blds-c3',
        docId: 'blds-2015',
        docName: 'Bộ luật Dân sự 2015',
        title: 'Điều 351: Trách nhiệm dân sự do vi phạm nghĩa vụ',
        article: 'Điều 351',
        clause: 'Khoản 1',
        snippet: 'Bên có nghĩa vụ mà không thực hiện hoặc thực hiện không đúng nghĩa vụ thì phải chịu trách nhiệm dân sự đối với bên có quyền. Trách nhiệm dân sự phát sinh khi có hành vi vi phạm nghĩa vụ, trừ trường hợp có thỏa thuận khác hoặc luật có quy định khác.'
      }
    ]
  },
  {
    id: 'qcbm-2025',
    name: 'Quy chế bảo mật thông tin nội bộ',
    code: 'QC-BM-01/2025',
    uploadDate: '2026-03-01',
    size: '450 KB',
    description: 'Quy chế nội bộ quy định về phân loại thông tin, nguyên tắc bảo mật và nghĩa vụ của nhân viên đối với tài sản trí tuệ.',
    status: 'ready',
    type: 'docx',
    chunks: [
      {
        id: 'qcbm-c1',
        docId: 'qcbm-2025',
        docName: 'Quy chế bảo mật thông tin nội bộ',
        title: 'Điều 3: Phân loại mức độ mật của thông tin',
        article: 'Điều 3',
        snippet: 'Thông tin trong doanh nghiệp được chia thành 3 mức độ bảo mật: \n1. Tự do (Public): Có thể chia sẻ rộng rãi ngoài doanh nghiệp.\n2. Nội bộ (Internal): Chỉ lưu hành giữa các nhân viên, không tiết lộ cho bên thứ ba.\n3. Nghiêm mật (Confidential): Dữ liệu chiến lược, danh sách khách hàng, mã nguồn phần mềm, báo cáo tài chính chưa công bố. Chỉ nhân viên được ủy quyền mới được phép tiếp cận.'
      },
      {
        id: 'qcbm-c2',
        docId: 'qcbm-2025',
        docName: 'Quy chế bảo mật thông tin nội bộ',
        title: 'Điều 7: Nghĩa vụ bảo mật của nhân viên',
        article: 'Điều 7',
        clause: 'Khoản 2',
        snippet: 'Nhân viên không được sử dụng email cá nhân (Gmail, Yahoo, v.v.) hoặc các công cụ lưu trữ đám mây không được phê duyệt (Personal Google Drive, Dropbox) để lưu trữ hoặc truyền gửi thông tin thuộc mức độ "Nội bộ" hoặc "Nghiêm mật". Mọi tài liệu công việc phải lưu trữ trên OneDrive doanh nghiệp cung cấp.'
      }
    ]
  }
];

export const suggestedPrompts = [
  {
    text: 'Điều kiện để doanh nghiệp được công nhận là doanh nghiệp xã hội?',
    icon: 'ShieldAlert',
    category: 'Pháp lý'
  },
  {
    text: 'So sánh sự khác nhau giữa Chi nhánh và Văn phòng đại diện?',
    icon: 'GitCompare',
    category: 'Doanh nghiệp'
  },
  {
    text: 'Giao dịch dân sự bị vô hiệu trong những trường hợp nào?',
    icon: 'Scale',
    category: 'Dân sự'
  },
  {
    text: 'Quy định sử dụng tài nguyên lưu trữ đám mây của nhân viên là gì?',
    icon: 'Lock',
    category: 'Quy chế nội bộ'
  }
];

export function getMockRAGResponse(
  query: string,
  activeDocIds: string[],
  settings: {
    searchMode: string;
    model: string;
    topK: number;
    similarityThreshold: number;
  }
): RAGResponse {
  const normalizedQuery = query.toLowerCase().trim();
  
  const searchableDocs = initialDocuments.filter(d => activeDocIds.includes(d.id));
  
  const allChunks: DocumentChunk[] = [];
  searchableDocs.forEach(d => {
    d.chunks.forEach(c => {
      let matchScore = 0.15;
      const queryWords = normalizedQuery.split(/\s+/);
      const chunkText = (c.title + ' ' + c.snippet + ' ' + c.article).toLowerCase();
      
      let matchedTerms = 0;
      queryWords.forEach(word => {
        if (word.length > 2 && chunkText.includes(word)) {
          matchedTerms++;
        }
      });
      
      if (matchedTerms > 0) {
        matchScore += (matchedTerms / queryWords.length) * 0.75;
      }
      
      const finalScore = Math.min(0.96, Math.max(0.15, matchScore));
      
      allChunks.push({
        ...c,
        score: parseFloat(finalScore.toFixed(2))
      });
    });
  });

  let retrievedChunks = allChunks
    .filter(c => c.score >= settings.similarityThreshold)
    .sort((a, b) => b.score - a.score);
  
  retrievedChunks = retrievedChunks.slice(0, settings.topK);

  const steps: RAGStep[] = [
    { name: 'Phân tích & Dịch câu hỏi (Query Expansion)', status: 'completed', details: `Từ khóa chính: "${query.substring(0, 30)}..." | Chế độ: ${settings.searchMode}` },
    { name: 'Truy xuất tài liệu từ Vector DB', status: 'completed', details: `Tìm thấy ${allChunks.length} chunks. Lọc lại ${retrievedChunks.length} chunks phù hợp (Threshold > ${settings.similarityThreshold})` },
    { name: 'Đánh giá xếp hạng chéo (Reranking)', status: 'completed', details: `Sử dụng mô hình ${settings.model === 'gpt-4o' ? 'GPT-4o Reranker' : 'BGE-Reranker-Large'}` },
    { name: 'Tạo Prompt ngữ cảnh & Gửi LLM', status: 'completed', details: `Context size: ~${retrievedChunks.reduce((acc, c) => acc + c.snippet.length, 0)} ký tự.` }
  ];

  let answer = '';
  
  const isSocialEnterprise = normalizedQuery.includes('doanh nghiệp xã hội') || normalizedQuery.includes('dnxh');
  const isBranchVsRep = normalizedQuery.includes('chi nhánh') && (normalizedQuery.includes('văn phòng đại diện') || normalizedQuery.includes('vpđd') || normalizedQuery.includes('khác nhau') || normalizedQuery.includes('so sánh'));
  const isVoidTransaction = normalizedQuery.includes('vô hiệu') || normalizedQuery.includes('điều kiện có hiệu lực');
  const isCloudStorage = normalizedQuery.includes('đám mây') || normalizedQuery.includes('lưu trữ') || normalizedQuery.includes('email cá nhân') || normalizedQuery.includes('bảo mật');

  if (isSocialEnterprise && searchableDocs.some(d => d.id === 'ldn-2020')) {
    const chunk = retrievedChunks.find(c => c.id === 'ldn-c1') || allChunks.find(c => c.id === 'ldn-c1');
    const scoreVal = chunk ? `(Độ tương đồng: ${Math.round(chunk.score * 100)}%)` : '';
    
    answer = `Dựa trên **Luật Doanh nghiệp 2020**, cụ thể là tại [Luật Doanh nghiệp 2020 - Điều 5](#cite-ldn-c1) ${scoreVal}, một doanh nghiệp để được công nhận là **Doanh nghiệp xã hội** phải đáp ứng đầy đủ **03 tiêu chí cốt lõi** sau đây:

1. **Về hình thức pháp lý**: Doanh nghiệp phải được đăng ký thành lập theo đúng quy định của Luật này (có thể là Công ty TNHH, Công ty Cổ phần, v.v.).
2. **Mục tiêu hoạt động**: Mục tiêu chính khi thành lập và vận hành là nhằm **giải quyết các vấn đề xã hội, môi trường** vì lợi ích cộng đồng.
3. **Cam kết tái đầu tư tài chính**: Doanh nghiệp phải sử dụng **ít nhất 51% tổng lợi nhuận sau thuế hằng năm** để tái đầu tư phục vụ trực tiếp cho các mục tiêu xã hội, môi trường như đã đăng ký.

Ngoài ra, người đại diện theo pháp luật của doanh nghiệp xã hội có nghĩa vụ tuân thủ các quy chế giám sát nghiêm ngặt từ cơ quan quản lý và các bên tài trợ. Nếu thay đổi mục tiêu hoặc không duy trì cam kết lợi nhuận, doanh nghiệp phải thông báo để chuyển đổi hình thức hoạt động.`;
  } 
  else if (isBranchVsRep && searchableDocs.some(d => d.id === 'ldn-2020')) {
    const chunk = retrievedChunks.find(c => c.id === 'ldn-c3') || allChunks.find(c => c.id === 'ldn-c3');
    const scoreVal = chunk ? `(Độ tương đồng: ${Math.round(chunk.score * 100)}%)` : '';

    answer = `Theo quy định tại [Luật Doanh nghiệp 2020 - Điều 44](#cite-ldn-c3) ${scoreVal}, **Chi nhánh** và **Văn phòng đại diện (VPĐD)** là hai hình thức đơn vị phụ thuộc của doanh nghiệp có sự khác biệt rõ rệt về mặt chức năng hoạt động pháp lý:

### 1. Chi nhánh
* **Chức năng**: Thực hiện **toàn bộ hoặc một phần chức năng** của doanh nghiệp. Điểm mấu chốt là chi nhánh **được quyền thực hiện hoạt động kinh doanh** trực tiếp sinh lời (phải phù hợp với ngành nghề đăng ký của công ty mẹ).
* **Đại diện**: Thực hiện cả chức năng đại diện theo ủy quyền của doanh nghiệp.
* **Kế toán & Thuế**: Có thể lựa chọn hình thức hạch toán độc lập (có bộ máy kế toán riêng, xuất hóa đơn riêng) hoặc hạch toán phụ thuộc công ty mẹ.

### 2. Văn phòng đại diện (VPĐD)
* **Chức năng**: Chỉ có nhiệm vụ **đại diện theo ủy quyền** để giao dịch, liên lạc, tìm hiểu thị trường, bảo vệ quyền lợi hợp pháp cho doanh nghiệp mẹ.
* **Kinh doanh**: **Hoàn toàn không có chức năng kinh doanh** và không được trực tiếp thực hiện hoạt động sinh lời, không được xuất hóa đơn thương mại.
* **Kế toán & Thuế**: Hạch toán phụ thuộc hoàn toàn vào công ty mẹ, không tự kê khai thuế thu nhập doanh nghiệp (trừ thuế TNCN cho nhân sự làm việc tại VPĐD).

> [!TIP]
> **Khuyên dùng:** Nếu doanh nghiệp muốn mở rộng địa điểm để trực tiếp bán hàng, cung cấp dịch vụ và ký kết hợp đồng thương mại, hãy thành lập **Chi nhánh**. Nếu chỉ muốn khảo sát thị trường, làm văn phòng liên lạc hoặc làm bộ phận chăm sóc khách hàng, hãy thành lập **Văn phòng đại diện** để tối giản hóa thủ tục thuế.`;
  }
  else if (isVoidTransaction && searchableDocs.some(d => d.id === 'blds-2015')) {
    const c1 = retrievedChunks.find(c => c.id === 'blds-c1') || allChunks.find(c => c.id === 'blds-c1');
    const c2 = retrievedChunks.find(c => c.id === 'blds-c2') || allChunks.find(c => c.id === 'blds-c2');
    
    answer = `Căn cứ theo các quy định trong **Bộ luật Dân sự 2015**, một giao dịch dân sự (bao gồm hợp đồng, thỏa thuận) sẽ bị coi là **vô hiệu** khi thiếu một trong các điều kiện quy định pháp luật. 

Cụ thể, theo [Bộ luật Dân sự 2015 - Điều 122](#cite-blds-c1), giao dịch không đáp ứng các điều kiện tại [Bộ luật Dân sự 2015 - Điều 117](#cite-blds-c2) thì vô hiệu. Các trường hợp cụ thể dẫn đến vô hiệu bao gồm:

1. **Vi phạm năng lực pháp lý/hành vi**: Chủ thể tham gia giao dịch không có năng lực pháp luật dân sự hoặc năng lực hành vi dân sự phù hợp (ví dụ: giao dịch do người chưa thành niên, người mất năng lực hành vi dân sự tự mình xác lập mà không có người đại diện đồng ý).
2. **Thiếu tính tự nguyện**: Các bên tham gia giao dịch không hoàn toàn tự nguyện (bị lừa dối, đe dọa, cưỡng ép, hoặc xác lập do giả tạo).
3. **Mục đích hoặc nội dung vi phạm pháp luật**: Nội dung giao dịch vi phạm điều cấm của luật hoặc trái đạo đức xã hội.
4. **Không tuân thủ hình thức bắt buộc**: Đối với một số giao dịch luật quy định bắt buộc phải bằng văn bản, phải công chứng/chứng thực (như chuyển nhượng quyền sử dụng đất, mua bán nhà ở) mà các bên không thực hiện, thì giao dịch có thể bị tuyên vô hiệu theo yêu cầu của một bên.

**Hậu quả pháp lý:** Khi giao dịch bị tuyên vô hiệu, các bên hoàn trả cho nhau những gì đã nhận, khôi phục lại tình trạng ban đầu và bên có lỗi gây thiệt hại phải bồi thường.`;
  }
  else if (isCloudStorage && searchableDocs.some(d => d.id === 'qcbm-2025')) {
    const chunk = retrievedChunks.find(c => c.id === 'qcbm-c2') || allChunks.find(c => c.id === 'qcbm-c2');
    const scoreVal = chunk ? `(Độ tương đồng: ${Math.round(chunk.score * 100)}%)` : '';

    answer = `Dựa trên tài liệu nội bộ [Quy chế bảo mật thông tin nội bộ - Điều 7](#cite-qcbm-c2) ${scoreVal}, quy định về việc sử dụng các dịch vụ lưu trữ đám mây đối với nhân viên công ty được thiết lập rất nghiêm ngặt nhằm tránh thất thoát dữ liệu:

* **Công cụ cấm sử dụng cá nhân**: Nhân viên **không được phép** sử dụng email cá nhân (ví dụ: Gmail, Yahoo Mail) hoặc các tài khoản đám mây cá nhân khác (Dropbox, Personal Google Drive, Box, iCloud cá nhân) để lưu trữ, sao chép hoặc truyền gửi thông tin thuộc diện **"Nội bộ"** hoặc **"Nghiêm mật"** (quy định tại [Điều 3](#cite-qcbm-c1)).
* **Công cụ bắt buộc sử dụng**: Mọi dữ liệu, tài liệu liên quan đến công việc phải được lưu trữ trên hạ tầng điện toán đám mây **OneDrive Doanh nghiệp** hoặc hệ thống Shared Drive do công ty trực tiếp cấp và quản lý dưới tài khoản định danh doanh nghiệp.
* **Chia sẻ cho bên thứ ba**: Nghiêm cấm chia sẻ quyền truy cập liên kết (link share) ra bên ngoài hệ thống công ty mà không được sự phê duyệt của Trưởng bộ phận hoặc Trưởng bộ phận An ninh thông tin (IT Security).

> [!WARNING]
> Mọi hành vi vi phạm quy định lưu trữ trên thiết bị/đám mây cá nhân tùy theo mức độ nghiêm trọng có thể bị xử lý kỷ luật lao động từ phê bình, đình chỉ công tác, hoặc sa thải theo quy định của Luật Lao động và Quy chế nhân sự công ty.`;
  }
  else {
    if (retrievedChunks.length > 0) {
      const topChunk = retrievedChunks[0];
      answer = `Hệ thống RAG đã tìm thấy ngữ cảnh liên quan trong **${topChunk.docName}** để trả lời câu hỏi của bạn. 

Dựa trên [${topChunk.docName} - ${topChunk.article}](#cite-${topChunk.id}):

> "${topChunk.snippet}"

**Tóm tắt & Phân tích:**
Thông tin này liên quan trực tiếp đến truy vấn của bạn về "${query}". Đây là quy định có hiệu lực của tổ chức/pháp luật. Hệ thống ghi nhận độ tương đồng ngữ nghĩa là **${Math.round(topChunk.score * 100)}%** dựa trên mô hình **${settings.model}** ở chế độ **${settings.searchMode}**.

Nếu bạn cần phân tích sâu hơn hoặc trích dẫn các tài liệu liên quan khác, vui lòng cung cấp câu hỏi chi tiết hơn.`;
    } else {
      answer = `Rất tiếc, hệ thống RAG không tìm thấy bất kỳ tài liệu hay ngữ cảnh nào có độ tương đồng lớn hơn ngưỡng **${settings.similarityThreshold}** trong các tài liệu đang hoạt động để trả lời cho câu hỏi: *"${query}"*.

**Gợi ý khắc phục:**
1. Hãy đảm bảo bạn đã tích chọn tài liệu phù hợp trong bảng điều khiển bên phải.
2. Giảm bớt ngưỡng tương đồng (Similarity Threshold) xuống mức thấp hơn (ví dụ: 0.2 hoặc 0.3) trong phần cài đặt RAG.
3. Thử đặt câu hỏi bằng các từ khóa pháp lý hoặc thuật ngữ chuyên môn có sẵn trong văn bản.
4. Tải thêm tài liệu liên quan thông qua tính năng **Tải lên tài liệu** ở thanh điều khiển bên phải.`;
    }
  }

  const processingTimeMs = Math.round(500 + Math.random() * 800);
  
  return {
    steps,
    citations: retrievedChunks,
    answer,
    processingTimeMs,
    tokensCount: {
      prompt: query.length + retrievedChunks.reduce((acc, c) => acc + c.snippet.length, 0),
      completion: answer.length
    }
  };
}

export function simulateDocumentProcessing(
  fileName: string,
  fileSize: number,
  onProgress: (stepIndex: number, text: string) => void
): Promise<MockDocument> {
  const steps = [
    'Đang tải tệp lên máy chủ lưu trữ tạm thời...',
    'Đang phát hiện loại tệp và quét virus...',
    'Đang thực hiện OCR trích xuất nội dung văn bản...',
    'Đang chia nhỏ văn bản thành các phân đoạn (Chunking) kích thước 500 tokens, overlap 10%...',
    'Đang tính toán các Vector Embeddings bằng mô hình text-embedding-3-small...',
    'Đang ghi chỉ mục Vector vào cơ sở dữ liệu Milvus/Qdrant Vector DB...',
    'Đang đồng bộ hóa cấu trúc siêu dữ liệu (Metadata Indexing) và hoàn tất...'
  ];

  return new Promise((resolve) => {
    let currentStep = 0;
    
    const interval = setInterval(() => {
      if (currentStep < steps.length) {
        onProgress(currentStep, steps[currentStep]);
        currentStep++;
      } else {
        clearInterval(interval);
        
        const docId = `upload-${Date.now()}`;
        const nameWithoutExt = fileName.replace(/\.[^/.]+$/, "");
        const ext = fileName.split('.').pop() as 'pdf' | 'docx' | 'txt' || 'pdf';
        
        const sizeStr = fileSize > 1024 * 1024 
          ? (fileSize / (1024 * 1024)).toFixed(1) + ' MB'
          : (fileSize / 1024).toFixed(0) + ' KB';

        const mockDoc: MockDocument = {
          id: docId,
          name: nameWithoutExt,
          code: `MOCK-${Math.floor(1000 + Math.random() * 9000)}/QC`,
          uploadDate: new Date().toISOString().split('T')[0],
          size: sizeStr,
          description: `Tài liệu tải lên bởi người dùng chứa thông tin về ${nameWithoutExt}.`,
          status: 'ready',
          type: ext,
          chunks: [
            {
              id: `${docId}-c1`,
              docId: docId,
              docName: nameWithoutExt,
              title: 'Phần 1: Nội dung chung của tài liệu tải lên',
              article: 'Chương I',
              clause: 'Mục 1',
              snippet: `Đoạn văn bản trích xuất từ tài liệu [${fileName}]: Đây là thông tin chi tiết liên quan đến các hướng dẫn hoạt động, quy chế hoặc quyết định của tổ chức. Hệ thống RAG đã lập chỉ mục vector thành công cho nội dung này để sẵn sàng trả lời các câu hỏi cụ thể liên quan đến quy định mới.`
            },
            {
              id: `${docId}-c2`,
              docId: docId,
              docName: nameWithoutExt,
              title: 'Phần 2: Các điều khoản thi hành và xử lý vi phạm',
              article: 'Chương II',
              clause: 'Mục 2',
              snippet: `Quy chuẩn thi hành được quy định trong tài liệu [${fileName}]: Mọi đơn vị trực thuộc và cá nhân liên quan có trách nhiệm thực hiện nghiêm túc quy định này từ ngày ban hành. Việc vi phạm sẽ chịu các chế tài kỷ luật nội bộ.`
            }
          ]
        };
        
        resolve(mockDoc);
      }
    }, 700);
  });
}
